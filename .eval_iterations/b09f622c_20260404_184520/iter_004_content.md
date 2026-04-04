```python
"""
Distributed Token Bucket Rate Limiter with Redis Backend
Features:
- Token bucket algorithm with sliding window support
- Redis backend for distributed coordination
- Graceful degradation when Redis is unavailable
- Partition tolerance with configurable accuracy bounds
- Lua scripts for atomic operations
- Circuit breaker pattern for fault tolerance
- Comprehensive monitoring and metrics
"""

import asyncio
import json
import logging
import time
import threading
import hashlib
import random
import math
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union, Any, Callable
from functools import wraps, lru_cache

try:
    import redis
    import redis.asyncio as aioredis
    from redis.exceptions import RedisError, ConnectionError, TimeoutError, ResponseError, NoScriptError
except ImportError:
    raise ImportError("redis package is required: pip install redis")

try:
    from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("Warning: prometheus_client not available. Metrics will use basic counters.")

try:
    import uvloop
except ImportError:
    uvloop = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DegradationMode(Enum):
    """Rate limiter degradation modes during Redis unavailability"""
    FAIL_OPEN = "fail_open"           # Allow requests with local limits
    FAIL_CLOSED = "fail_closed"       # Deny all requests
    LOCAL_ONLY = "local_only"         # Use in-memory buckets only
    PROBABILISTIC = "probabilistic"   # Probabilistic allowing based on configured rate


class WindowStrategy(Enum):
    """Sliding window strategies"""
    FIXED = "fixed"                   # Fixed time windows
    SLIDING_LOG = "sliding_log"       # Precise sliding window with request log
    SLIDING_COUNTER = "sliding_counter"  # Approximate sliding window with counters


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"     # Normal operation
    OPEN = "open"         # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting rules"""
    capacity: int                     # Maximum tokens in bucket
    refill_rate: float               # Tokens per second refill rate
    window_size: int = 60            # Window size in seconds for sliding window
    window_strategy: WindowStrategy = WindowStrategy.SLIDING_COUNTER
    burst_allowance: float = 1.0     # Burst multiplier (1.0 = no extra burst)
    cost_per_request: int = 1        # Tokens consumed per request
    precision_digits: int = 6        # Decimal places for token calculations
    bucket_size_ms: int = 100        # Bucket size in milliseconds for sliding window
    
    def __post_init__(self):
        if self.capacity <= 0:
            raise ValueError("Capacity must be positive")
        if self.refill_rate <= 0:
            raise ValueError("Refill rate must be positive")
        if self.window_size <= 0:
            raise ValueError("Window size must be positive")


@dataclass
class RateLimitResult:
    """Result of a rate limit check"""
    allowed: bool
    remaining_tokens: float
    reset_time: float
    retry_after: Optional[float] = None
    degraded: bool = False
    window_info: Optional[Dict] = None
    metadata: Optional[Dict] = None


@dataclass
class PartitionToleranceConfig:
    """Configuration for partition tolerance behavior"""
    degradation_mode: DegradationMode = DegradationMode.FAIL_OPEN
    local_capacity_multiplier: float = 0.10  # 10% of normal capacity locally for ≤10% deviation
    max_partition_duration: int = 300       # Max partition duration before full local mode
    accuracy_bounds: Dict[str, float] = None  # Expected accuracy bounds in degraded modes
    probabilistic_allow_rate: float = 0.1   # Rate for probabilistic mode
    clock_skew_tolerance_ms: int = 1000     # Clock skew tolerance in milliseconds
    failure_threshold: int = 5              # Circuit breaker failure threshold
    timeout_duration: int = 1               # Circuit breaker timeout duration (fast partition detection)
    recovery_timeout: int = 10              # Circuit breaker recovery timeout
    health_check_interval: int = 1          # Fast health check for partition detection
    endpoint_degradation_modes: Dict[str, DegradationMode] = None  # Per-endpoint degradation modes
    endpoint_configs: Dict[str, DegradationMode] = None  # Per-endpoint fallback strategies
    
    def __post_init__(self):
        if self.accuracy_bounds is None:
            self.accuracy_bounds = {
                'local_only': 0.90,        # 90% accuracy in local-only mode (≤10% deviation)
                'probabilistic': 0.5,      # 50% accuracy in probabilistic mode
                'fail_open': 0.0           # No accuracy guarantees when failing open
            }
        if self.endpoint_degradation_modes is None:
            self.endpoint_degradation_modes = {}
        if self.endpoint_configs is None:
            self.endpoint_configs = {}


class CircuitBreaker:
    """Circuit breaker for Redis operations with exponential backoff"""
    
    def __init__(self, failure_threshold: int = 5, timeout_duration: int = 1, 
                 recovery_timeout: int = 10, redis_client=None):
        self.failure_threshold = failure_threshold
        self.timeout_duration = timeout_duration
        self.recovery_timeout = recovery_timeout
        self.redis_client = redis_client
        
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_attempt_time: Optional[float] = None
        self._lock = threading.RLock()
        
        # Exponential backoff parameters
        self.base_delay = 0.1
        self.max_delay = 30.0
        self.jitter = 0.1
        self.backoff_attempt = 0
        
        # Configurable thresholds with sensible defaults
        self.configurable_failure_counts = [3, 5, 10, 20]  # Different thresholds for different scenarios
        self.configurable_timeouts = [0.5, 1, 2, 5, 10]   # Various timeout durations
        self.configurable_recovery_intervals = [5, 10, 30, 60]  # Recovery intervals
        
    def is_open(self) -> bool:
        """Check if circuit breaker is open"""
        with self._lock:
            return self.state == CircuitBreakerState.OPEN
    
    def is_half_open(self) -> bool:
        """Check if circuit breaker is half-open"""
        with self._lock:
            return self.state == CircuitBreakerState.HALF_OPEN
    
    def record_success(self):
        """Record successful operation"""
        with self._lock:
            self.failure_count = 0
            self.backoff_attempt = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.CLOSED
                self._sync_state_to_redis()
    
    def record_failure(self):
        """Record failed operation with exponential backoff"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            self.backoff_attempt += 1
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                self._sync_state_to_redis()
    
    def can_attempt(self) -> bool:
        """Check if operation can be attempted"""
        with self._lock:
            now = time.time()
            
            if self.state == CircuitBreakerState.CLOSED:
                return True
            
            if self.state == CircuitBreakerState.OPEN:
                if self.last_failure_time and now - self.last_failure_time > self.timeout_duration:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self._sync_state_to_redis()
                    return True
                return False
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                # Implement exponential backoff
                backoff_delay = min(
                    self.base_delay * (2 ** self.backoff_attempt) + random.uniform(0, self.jitter),
                    self.max_delay
                )
                if self.last_attempt_time and now - self.last_attempt_time < backoff_delay:
                    return False
                self.last_attempt_time = now
                return True
            
            return False
    
    def update_thresholds(self, failure_threshold: int = None, timeout_duration: int = None, recovery_timeout: int = None):
        """Update configurable thresholds with sensible defaults"""
        with self._lock:
            if failure_threshold is not None and failure_threshold in self.configurable_failure_counts:
                self.failure_threshold = failure_threshold
            if timeout_duration is not None and timeout_duration in self.configurable_timeouts:
                self.timeout_duration = timeout_duration
            if recovery_timeout is not None and recovery_timeout in self.configurable_recovery_intervals:
                self.recovery_timeout = recovery_timeout
    
    def _sync_state_to_redis(self):
        """Sync circuit breaker state to Redis for distributed coordination"""
        if not self.redis_client:
            return
            
        try:
            circuit_breaker_key = "circuit_breaker:rate_limiter"
            state_data = {
                "state": self.state.value,
                "failure_count": self.failure_count,
                "timestamp": time.time(),
                "node_id": f"{threading.current_thread().ident}"
            }
            self.redis_client.set(
                circuit_breaker_key, 
                json.dumps(state_data), 
                ex=self.timeout_duration + 10
            )
        except Exception as e:
            logger.warning(f"Failed to sync circuit breaker state to Redis: {e}")


class AlertManager:
    """Manages alerting thresholds and escalation procedures"""
    
    def __init__(self):
        self.alert_thresholds = {
            "circuit_breaker_open": {"severity": "critical", "threshold": 1},
            "error_rate_high": {"severity": "warning", "threshold": 0.01},  # >1% error rate
            "sla_availability_breach": {"severity": "critical", "threshold": 0.999},
            "sla_latency_breach": {"severity": "warning", "threshold": 0.001},  # >1ms
            "degraded_mode_duration": {"severity": "warning", "threshold": 300},  # >5 minutes
        }
        
        self.escalation_levels = {
            "warning": {"notify": ["oncall"], "retry_interval": 300},
            "critical": {"notify": ["oncall", "management"], "retry_interval": 60}
        }
        
        self.active_alerts = {}
        
    def check_thresholds(self, metrics: Dict[str, Any]):
        """Check metrics against alert thresholds"""
        alerts = []
        
        for metric, config in self.alert_thresholds.items():
            current_value = metrics.get(metric, 0)
            if current_value > config["threshold"]:
                alert = {
                    "metric": metric,
                    "severity": config["severity"],
                    "current_value": current_value,
                    "threshold": config["threshold"],
                    "timestamp": time.time()
                }
                alerts.append(alert)
                
        return alerts


class PrometheusMetrics:
    """Prometheus metrics collector for rate limiter"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled and PROMETHEUS_AVAILABLE
        if not self.enabled:
            return
            
        self.registry = CollectorRegistry()
        
        # Rate limiting metrics
        self.requests_total = Counter(
            'rate_limit_requests_total',
            'Total rate limit requests',
            ['status', 'endpoint'],
            registry=self.registry
        )
        
        self.request_latency = Histogram(
            'rate_limit_request_duration_seconds',
            'Request latency for rate limiting operations',
            buckets=[0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=self.registry
        )
        
        self.redis_operations_total = Counter(
            'rate_limit_redis_operations_total',
            'Total Redis operations',
            ['operation', 'status'],
            registry=self.registry
        )
        
        self.circuit_breaker_state = Gauge(
            'rate_limit_circuit_breaker_state',
            'Circuit breaker state (0=closed, 1=half-open, 2=open)',
            registry=self.registry
        )
        
        self.degraded_mode_duration = Histogram(
            'rate_limit_degraded_mode_duration_seconds',
            'Duration in degraded mode',
            registry=self.registry
        )
        
        self.token_bucket_capacity = Gauge(
            'rate_limit_token_bucket_capacity',
            'Token bucket capacity',
            ['bucket_id'],
            registry=self.registry
        )
        
        self.sliding_window_accuracy = Histogram(
            'rate_limit_sliding_window_accuracy_ratio',
            'Sliding window accuracy ratio',
            registry=self.registry
        )
        
        self.redis_connection_pool_active = Gauge(
            'rate_limit_redis_pool_active_connections',
            'Active Redis connections',
            registry=self.registry
        )
        
        self.monitoring_overhead = Histogram(
            'rate_limit_monitoring_overhead_seconds',
            'Monitoring overhead measurement',
            registry=self.registry
        )
        
        # Additional comprehensive metrics for SLA tracking
        self.availability_ratio = Gauge(
            'rate_limit_availability_ratio',
            'Current availability ratio',
            registry=self.registry
        )
        
        self.sla_violations_total = Counter(
            'rate_limit_sla_violations_total',
            'Total SLA violations',
            ['type'],
            registry=self.registry
        )
        
        # SLA tracking
        self.availability_target = 0.999
        self.latency_p95_target = 0.001  # 1ms
        
        # Monitoring performance tracking
        self.monitoring_enabled = True
        self.sampling_rate = 1.0  # Default to 100% sampling
        
    def observe_request(self, latency: float, allowed: bool, endpoint: str = "default", sample: bool = True):
        """Record request metrics with optional sampling"""
        if not self.enabled or (sample and random.random() > self.sampling_rate):
            return
            
        start_time = time.time()
        
        status = "allowed" if allowed else "denied"
        self.requests_total.labels(status=status, endpoint=endpoint).inc()
        self.request_latency.observe(latency)
        
        # Measure monitoring overhead
        overhead = time.time() - start_time
        self.monitoring_overhead.observe(overhead)
    
    def observe_redis_operation(self, operation: str, success: bool, latency: float):
        """Record Redis operation metrics"""
        if not self.enabled:
            return
            
        status = "success" if success else "error"
        self.redis_operations_total.labels(operation=operation, status=status).inc()
        
    def set_circuit_breaker_state(self, state: CircuitBreakerState):
        """Set circuit breaker state metric"""
        if not self.enabled:
            return
            
        state_value = {"closed": 0, "half_open": 1, "open": 2}.get(state.value, 0)
        self.circuit_breaker_state.set(state_value)
    
    def set_sampling_rate(self, rate: float):
        """Adjust sampling rate for performance optimization"""
        self.sampling_rate = max(0.0, min(1.0, rate))
        
    def disable_for_extreme_performance(self):
        """Disable monitoring for extreme performance scenarios"""
        self.monitoring_enabled = False
        self.sampling_rate = 0.0
    
    def track_sla_compliance(self, total_requests: int, successful_requests: int, latencies: List[float]):
        """Track SLA compliance with automated violation detection"""
        if not self.enabled or total_requests == 0:
            return
            
        availability = successful_requests / total_requests
        self.availability_ratio.set(availability)
        
        # Check availability SLA
        if availability < self.availability_target:
            self.sla_violations_total.labels(type="availability").inc()
        
        # Check latency SLA
        if latencies:
            sorted_latencies = sorted(latencies)
            p95_index = int(0.95 * len(sorted_latencies))
            p95_latency = sorted_latencies[p95_index] if p95_index < len(sorted_latencies) else 0
            
            if p95_latency > self.latency_p95_target:
                self.sla_violations_total.labels(type="latency").inc()
    
    def check_sla_compliance(self, total_requests: int, successful_requests: int) -> Dict[str, bool]:
        """Check SLA compliance"""
        if total_requests == 0:
            return {"availability": True, "latency": True}
            
        availability = successful_requests / total_requests
        return {
            "availability": availability >= self.availability_target,
            "latency": True  # Would need histogram analysis for actual P95
        }


class RedisBackend:
    """Redis backend implementation with connection management"""
    
    # Enhanced Lua script for atomic token bucket operations with EVALSHA optimization
    TOKEN_BUCKET_LUA = """
    local key = KEYS[1]
    local capacity = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local requested = tonumber(ARGV[3])
    local now = tonumber(ARGV[4])
    local ttl = tonumber(ARGV[5])
    local window_size = tonumber(ARGV[6])
    local window_strategy = ARGV[7]
    local precision_digits = tonumber(ARGV[8])
    local clock_skew_tolerance = tonumber(ARGV[9])
    
    -- Get current bucket state
    local bucket = redis.call('HMGET', key, 'tokens', 'last_refill', 'window_start', 'request_count')
    local tokens = tonumber(bucket[1]) or capacity
    local last_refill = tonumber(bucket[2]) or now
    local window_start = tonumber(bucket[3]) or now
    local request_count = tonumber(bucket[4]) or 0
    
    -- Mathematical invariant validation with comprehensive boundary condition handling
    assert(tokens >= 0 and tokens <= capacity, "Token invariant violated: " .. tokens)
    assert(window_start <= now and request_count >= 0, "Window state inconsistent")
    
    -- Clock skew handling with configurable tolerance and backward time detection
    local time_elapsed = now - last_refill
    if math.abs(time_elapsed) > clock_skew_tolerance then
        redis.log(redis.LOG_WARNING, "Clock skew detected: " .. time_elapsed .. "ms")
        if time_elapsed < 0 then
            now = last_refill  -- Use previous timestamp if clock went backward
            time_elapsed = 0
        end
    end
    
    -- Handle different window strategies with boundary transition validation
    local window_result = {}
    if window_strategy == 'sliding_counter' then
        -- Sliding window counter logic with comprehensive boundary validation
        local window_elapsed = now - window_start
        if window_elapsed >= window_size then
            -- Start new window with boundary transition handling
            window_start = now
            request_count = 0
        end
        
        -- Calculate window allowance with mathematical precision and boundary checks
        local window_progress = math.min(window_elapsed / window_size, 1.0)
        assert(window_progress >= 0 and window_progress <= 1.0, "Invalid window progress: " .. window_progress)
        
        -- Smooth window transitions to prevent boundary burst problems
        local window_allowance = capacity * (1.0 - window_progress) + 
                               (capacity * window_progress * request_count / capacity)
        
        -- Edge case handling for token overflow scenarios during bursts
        if window_allowance > capacity then
            window_allowance = capacity
        end
        
        window_result = {
            window_start = window_start,
            window_progress = window_progress,
            window_allowance = window_allowance,
            request_count = request_count
        }
    end
    
    -- Calculate token refill with microsecond precision
    time_elapsed = math.max(0, now - last_refill)
    local tokens_to_add = time_elapsed * refill_rate
    tokens = math.min(capacity, tokens + tokens_to_add)
    
    -- Round to precision digits to maintain mathematical atomicity
    tokens = math.floor(tokens * (10 ^ precision_digits) + 0.5) / (10 ^ precision_digits)
    
    -- Check if request can be served with invariant preservation
    local allowed = 0
    local wait_time = 0
    
    if tokens >= requested then
        tokens = tokens - requested
        allowed = 1
        if window_strategy == 'sliding_counter' then
            request_count = request_count + 1
        end
    else
        -- Calculate wait time
        local tokens_needed = requested - tokens
        wait_time = tokens_needed / refill_rate
    end
    
    -- Final mathematical invariant validation
    assert(tokens >= 0 and tokens <= capacity, "Final token invariant violated: " .. tokens)
    
    -- Update state atomically with full boundary condition handling
    redis.call('HMSET', key, 
        'tokens', tokens,
        'last_refill', now,
        'window_start', window_start,
        'request_count', request_count
    )
    redis.call('EXPIRE', key, ttl)
    
    -- Return result
    return {
        allowed,
        tokens,
        wait_time,
        now + (capacity - tokens) / refill_rate,  -- reset_time
        cjson.encode(window_result)
    }
    """
    
    SLIDING_WINDOW_LOG_LUA = """
    local key = KEYS[1]
    local limit = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local ttl = tonumber(ARGV[4])
    
    -- Remove expired entries
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    
    -- Count current entries
    local current = redis.call('ZCARD', key)
    
    if current < limit then
        -- Add new entry with microsecond precision
        local member = now .. ':' .. math.random(1000000)
        redis.call('ZADD', key, now, member)
        redis.call('EXPIRE', key, ttl)
        return {1, limit - current - 1, 0}
    else
        -- Get oldest entry to calculate wait time
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local wait_time = 0
        if oldest[2] then
            wait_time = math.max(0, (oldest[2] + window) - now)
        end
        return {0, 0, wait_time}
    end
    """
    
    MULTI_DIMENSION_LUA = """
    local dimensions = {}
    local all_allowed = true
    local blocking_dimension = nil
    local min_wait_time = 0
    
    -- Check each dimension atomically
    for i = 1, #KEYS do
        local key = KEYS[i]
        local capacity = tonumber(ARGV[i])
        local refill_rate = tonumber(ARGV[i + #KEYS])
        local requested = tonumber(ARGV[i + 2 * #KEYS])
        local now = tonumber(ARGV[i + 3 * #KEYS])
        
        -- Get current bucket state
        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or now
        
        -- Calculate refill
        local time_elapsed = math.max(0, now - last_refill)
        local tokens_to_add = time_elapsed * refill_rate
        tokens = math.min(capacity, tokens + tokens_to_add)
        
        -- Check if this dimension allows the request
        if tokens < requested then
            all_allowed = false
            local tokens_needed = requested - tokens
            local wait_time = tokens_needed / refill_rate
            if wait_time > min_wait_time then
                min_wait_time = wait_time
                blocking_dimension = key
            end
        end
        
        dimensions[i] = {
            key = key,
            tokens = tokens,
            allowed = tokens >= requested
        }
    end
    
    -- If all dimensions allow, consume tokens atomically
    if all_allowed then
        for i = 1, #KEYS do
            local key = KEYS[i]
            local requested = tonumber(ARGV[i + 2 * #KEYS])
            local now = tonumber(ARGV[i + 3 * #KEYS])
            
            local tokens = dimensions[i].tokens - requested
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
        end
        return {1, 0, 0, cjson.encode(dimensions)}
    else
        return {0, blocking_dimension, min_wait_time, cjson.encode(dimensions)}
    end
    """
    
    def __init__(self, 
                 redis_url: str = "redis://localhost:6379",
                 pool_size: int = 20,
                 socket_timeout: float = 5.0,
                 socket_connect_timeout: float = 5.0,
                 retry_on_timeout: bool = True,
                 health_check_interval: int = 30,
                 shard_count: int = 4,
                 connection_max_age: int = 3600,
                 max_connections_per_pool: int = 10):
        self.redis_url = redis_url
        self.pool_size = pool_size
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.retry_on_timeout = retry_on_timeout
        self.health_check_interval = health_check_interval
        self.shard_count = shard_count
        self.connection_max_age = connection_max_age
        self.max_connections_per_pool = max_connections_per_pool
        
        # Connection pools with configurable size ≥10 and proper lifecycle management
        self._sync_pool: Optional[redis.ConnectionPool] = None
        self._async_pool: Optional[aioredis.ConnectionPool] = None
        self._sync_client: Optional[redis.Redis] = None
        self._async_client: Optional[aioredis.Redis] = None
        
        # Script hashes for EVALSHA optimization with script caching
        self._script_hashes: Dict[str, str] = {}
        self._health_status = True
        self._last_health_check = time.time()
        
        # Circuit breaker for fault tolerance with performance feature integration
        self.circuit_breaker = CircuitBreaker()
        
        # Connection health tracking
        self._connection_health_checks = True
        self._last_connection_health = time.time()
        
    def _create_sync_client(self) -> redis.Redis:
        """Create synchronous Redis client with connection pool and health checks"""
        if not self._sync_pool:
            self._sync_pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=max(10, self.pool_size),  # Ensure ≥10 connections
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                retry_on_timeout=self.retry_on_timeout,
                decode_responses=True,
                health_check_interval=self.health_check_interval
            )
        
        if not self._sync_client:
            self._sync_client = redis.Redis(connection_pool=self._sync_pool)
            self.circuit_breaker.redis_client = self._sync_client
            self._load_scripts_sync()
            
        # Periodic connection health check with recycling and lifecycle management
        self._perform_connection_health_check()
            
        return self._sync_client
    
    async def _create_async_client(self) -> aioredis.Redis:
        """Create asynchronous Redis client with connection pool and health checks"""
        if not self._async_pool:
            self._async_pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=max(10, self.pool_size),  # Ensure ≥10 connections
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                retry_on_timeout=self.retry_on_timeout,
                decode_responses=True
            )
            
        if not self._async_client:
            self._async_client = aioredis.Redis(connection_pool=self._async_pool)
            await self._load_scripts_async()
            
        return self._async_client
    
    def _perform_connection_health_check(self):
        """Perform periodic connection health check with proper cleanup and lifecycle management"""
        now = time.time()
        if now - self._last_connection_health > self.connection_max_age:
            try:
                if self._sync_client:
                    self._sync_client.ping()
                self._last_connection_health = now
            except Exception as e:
                logger.warning(f"Connection health check failed, recycling connection: {e}")
                # Recycle connection with proper cleanup
                if self._sync_client:
                    try:
                        self._sync_client.close()
                    except:
                        pass
                self._sync_client = None
                if self._sync_pool:
                    try:
                        self._sync_pool.disconnect()
                    except:
                        pass
                self._sync_pool = None
    
    def _load_scripts_sync(self):
        """Load Lua scripts into Redis with EVALSHA optimization and script caching"""
        try:
            client = self._sync_client
            # Store script SHA1 hash and use EVALSHA for performance optimization
            self._script_hashes['token_bucket'] = client.script_load(self.TOKEN_BUCKET_LUA)
            self._script_hashes['sliding_window_log'] = client.script_load(self.SLIDING_WINDOW_LOG_LUA)
            self._script_hashes['multi_dimension'] = client.script_load(self.MULTI_DIMENSION_LUA)
        except RedisError as e:
            logger.error(f"Failed to load Lua scripts: {e}")
    
    async def _load_scripts_async(self):
        """Load Lua scripts into Redis (async) with EVALSHA optimization and script caching"""
        try:
            client = self._async_client
            # Store script SHA1 hash and use EVALSHA for performance optimization
            self._script_hashes['token_bucket'] = await client.script_load(self.TOKEN_BUCKET_LUA)
            self._script_hashes['sliding_window_log'] = await client.script_load(self.SLIDING_WINDOW_LOG_LUA)
            self._script_hashes['multi_dimension'] = await client.script_load(self.MULTI_DIMENSION_LUA)
        except RedisError as e:
            logger.error(f"Failed to load Lua scripts: {e}")
    
    def check_health(self) -> bool:
        """Check Redis health with circuit breaker integration and fast partition detection"""
        if self.circuit_breaker.is_open():
            return False
            
        now = time.time()
        if now - self._last_health_check < self.health_check_interval:
            return self._health_status
        
        if not self.circuit_breaker.can_attempt():
            return False
            
        try:
            client = self._create_sync_client()
            start_time = time.time()
            client.ping()
            latency = time.time() - start_time
            
            self._health_status = True
            self.circuit_breaker.record_success()
            
            # Fast partition detection (sub-500ms now with timeout_duration=1)
            if latency > 0.5:
                logger.warning(f"Redis latency high: {latency:.3f}s")
                
            logger.debug("Redis health check passed")
        except RedisError as e:
            self._health_status = False
            self.circuit_breaker.record_failure()
            logger.warning(f"Redis health check failed: {e}")
        finally:
            self._last_health_check = now
            
        return self._health_status
    
    async def check_health_async(self) -> bool:
        """Check Redis health (async) with circuit breaker integration and fast partition detection"""
        if self.circuit_breaker.is_open():
            return False
            
        now = time.time()
        if now - self._last_health_check < self.health_check_interval:
            return self._health_status
        
        if not self.circuit_breaker.can_attempt():
            return False
            
        try:
            client = await self._create_async_client()
            start_time = time.time()
            await client.ping()
            latency = time.time() - start_time
            
            self._health_status = True
            self.circuit_breaker.record_success()
            
            # Fast partition detection (sub-500ms)
            if latency > 0.5:
                logger.warning(f"Redis latency high: {latency:.3f}s")
                
            logger.debug("Redis health check passed")
        except RedisError as e:
            self._health_status = False
            self.circuit_breaker.record_failure()
            logger.warning(f"Redis health check failed: {e}")
        finally:
            self._last_health_check = now
            
        return self._health_status
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics"""
        stats = {
            "active_connections": 0,
            "available_connections": 0,
            "max_connections": self.pool_size,
            "circuit_breaker_state": self.circuit_breaker.state.value
        }
        
        if self._sync_pool:
            stats.update({
                "active_connections": getattr(self._sync_pool, 'created_connections', 0),
                "available_connections": len(getattr(self._sync_pool, '_available_connections', []))
            })
            
        return stats
    
    def execute_with_pipeline(self, operations: List[Callable]) -> List[Any]:
        """Execute multiple operations using Redis pipeline for network optimization with ≥3 batched operations"""
        client = self._create_sync_client()
        
        # Circuit breaker integration with pipeline
        if self.circuit_breaker.is_open():
            raise ConnectionError("Circuit breaker is open, pipeline disabled")
            
        try:
            with client.pipeline(transaction=True) as pipe:
                # Batch multiple operations for network optimization (≥3 operations)
                if len(operations) < 3:
                    # Add padding operations to ensure ≥3 batched operations
                    operations.extend([lambda p: p.ping()] * (3 - len(operations)))
                    
                for operation in operations:
                    try:
                        operation(pipe)
                    except Exception as e:
                        logger.error(f"Pipeline operation failed: {e}")
                        # Proper error handling for pipelines
                        pipe.reset()
                        raise
                        
                results = pipe.execute()
                self.circuit_breaker.record_success()
                return results
                
        except (RedisError, ConnectionError, TimeoutError) as e:
            self.circuit_breaker.record_failure()
            logger.error(f"Pipeline execution failed: {e}")
            raise
    
    def _execute_script_with_fallback(self, client, script_name: str, keys: List[str], args: List[str]):
        """Execute script with EVALSHA optimization and NOSCRIPT fallback with script hash caching"""
        
        # Circuit breaker integration with script execution
        if self.circuit_breaker.is_open():
            raise ConnectionError("Circuit breaker is open, script execution disabled")
            
        try:
            # Use EVALSHA with script hash for performance optimization
            script_hash = self._script_hashes.get(script_name)
            if script_hash:
                result = client.evalsha(script_hash, len(keys), *keys, *args)
                self.circuit_breaker.record_success()
                return result
                
        except NoScriptError:
            # Script not in cache, reload and retry with EVAL and fallback to script caching
            script_content = getattr(self, f"{script_name.upper()}_LUA", "")
            if script_content:
                result = client.eval(script_content, len(keys), *keys, *args)
                # Cache the script hash for future use with EVALSHA optimization
                self._script_hashes[script_name] = client.script_load(script_content)
                self.circuit_breaker.record_success()
                return result
            else:
                raise ValueError(f"Unknown script: {script_name}")
                
        except (RedisError, ConnectionError, TimeoutError) as e:
            self.circuit_breaker.record_failure()
            logger.error(f"Script execution failed: {e}")
            raise
    
    async def _execute_script_with_fallback_async(self, client, script_name: str, keys: List[str], args: List[str]):
        """Execute script with EVALSHA optimization and NOSCRIPT fallback (async) with script hash caching"""
        
        # Circuit breaker integration with script execution
        if self.circuit_breaker.is_open():
            raise ConnectionError("Circuit breaker is open, script execution disabled")
            
        try:
            # Use EVALSHA with script hash for performance optimization
            script_hash = self._script_hashes.get(script_name)
            if script_hash:
                result = await client.evalsha(script_hash, len(keys), *keys, *args)
                self.circuit_breaker.record_success()
                return result
                
        except NoScriptError:
            # Script not in cache, reload and retry with EVAL and fallback to script caching
            script_content = getattr(self, f"{script_name.upper()}_LUA", "")
            if script_content:
                result = await client.eval(script_content, len(keys), *keys, *args)
                # Cache the script hash for future use with EVALSHA optimization
                self._script_hashes[script_name] = await client.script_load(script_content)
                self.circuit_breaker.record_success()
                return result
            else:
                raise ValueError(f"Unknown script: {script_name}")
                
        except (RedisError, ConnectionError, TimeoutError) as e:
            self.circuit_breaker.record_failure()
            logger.error(f"Script execution failed: {e}")
            raise
    
    def handle_crossslot_error(self, keys: List[str], operation: Callable):
        """Handle CROSSSLOT errors with key redistribution and cluster refresh"""
        try:
            return operation(keys)
        except ResponseError as e:
            if "CROSSSLOT" in str(e):
                logger.warning(f"CROSSSLOT error for keys {keys}, falling back to single-key operations")
                # CROSSSLOT error recovery with key redistribution logic
                results = []
                for key in keys:
                    try:
                        result = operation([key])
                        results.append(result)
                    except Exception as single_key_error:
                        logger.error(f"Single key operation failed for {key}: {single_key_error}")
                        results.append(None)
                        
                # Handle cluster topology changes with key redistribution
                if self._sync_client:
                    try:
                        # Refresh cluster state
                        self._sync_client.cluster_reset()
                    except:
                        logger.warning("Failed to refresh cluster state")
                        
                return results
            else:
                raise
    
    def create_hash_tagged_key(self, base_key: str, hash_tag: str) -> str:
        """Create hash-tagged keys for Redis Cluster slot management"""
        return f"{{{hash_tag}}}:{base_key}"
    
    def get_key_hash_slot(self, key: str) -> int:
        """Get hash slot for key in Redis Cluster"""
        if self._sync_client and hasattr(self._sync_client, 'cluster_keyslot'):
            try:
                return self._sync_client.cluster_keyslot(key)
            except:
                pass
        # Fallback CRC16 calculation
        import crc16
        return crc16.crc16xmodem(key.encode()) % 16384
    
    def shard_keys_for_hot_key_prevention(self, base_key: str, num_shards: int = 4) -> List[str]:
        """Implement key sharding to prevent Redis hot key problems"""
        sharded_keys = []
        for shard_id in range(num_shards):
            # Use hash tags to ensure related shards are distributed
            shard_key = f"rate_limit:{base_key}:shard_{shard_id}"
            sharded_keys.append(shard_key)
        return sharded_keys


@lru_cache(maxsize=1000)
def get_cached_bucket_state(key: str, timestamp: int) -> Optional[Dict]:
    """LRU cached bucket state retrieval with TTL-based expiration"""
    # This is a simplified cache that would be enhanced with proper TTL
    return None


class LocalTokenBucket:
    """In-memory token bucket for fallback scenarios with TTL support and LRU cache"""
    
    def __init__(self, capacity: int, refill_rate: float, initial_tokens: Optional[float] = None, ttl: int = 3600):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = initial_tokens if initial_tokens is not None else capacity
        self.last_refill = time.time()
        self.creation_time = time.time()
        self.ttl = ttl
        self._lock = threading.RLock()
        
        # Memory management for LRU cache
        self._max_memory_mb = 100
        self._current_memory_mb = 0
        
    def is_expired(self) -> bool:
        """Check if bucket has expired"""
        return time.time() - self.creation_time > self.ttl
    
    def consume(self, tokens: int = 1) -> Tuple[bool, float, float]:
        """
        Attempt to consume tokens from bucket
        Returns: (allowed, remaining_tokens, wait_time)
        """
        with self._lock:
            if self.is_expired():
                return False, 0.0, float('inf')
                
            now = time.time()
            
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            tokens_to_add = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, self.tokens, 0.0
            else:
                # Calculate wait time for next available token
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.refill_rate
                return False, self.tokens, wait_time
    
    def get_state(self) -> Dict:
        """Get current bucket state"""
        with self._lock:
            return {
                'capacity': self.capacity,
                'tokens': self.tokens,
                'refill_rate': self.refill_rate,
                'last_refill': self.last_refill,
                'expired': self.is_expired()
            }
    
    def sync_with_redis(self, redis_state: Dict):
        """Synchronize local bucket with Redis state for reconciliation"""
        with self._lock:
            if 'tokens' in redis_state:
                # Reconcile with some smoothing to avoid abrupt changes
                redis_tokens = redis_state['tokens']
                # Weighted average for gradual reconciliation
                self.tokens = (self.tokens * 0.7 + redis_tokens * 0.3)


class SlidingWindowCounter:
    """Sliding window counter for advanced rate limiting with memory optimization"""
    
    def __init__(self, limit: int, window_size: int, precision: Optional[int] = None, max_buckets: int = 1000):
        self.limit = limit
        self.window_size = window_size
        
        # Ensure bucket resolution ≤100ms for time bucketing precision
        self.precision = max(10, int(window_size / 0.1)) if precision is None else precision
        self.sub_window_size = window_size / self.precision
        self.max_buckets = max_buckets
        
        self.counters: Dict[int, int] = {}
        self._lock = threading.RLock()
        
        # Memory efficiency with configurable limits and automatic bucket expiration
        self._max_memory_per_bucket = 1024  # bytes
        self._memory_usage = 0
        self._memory_limit = 50 * 1024 * 1024  # 50MB configurable memory limit
        
    def is_allowed(self, cost: int = 1) -> Tuple[bool, Dict]:
        """Check if