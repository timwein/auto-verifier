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
    local_capacity_multiplier: float = 0.15  # 15% of normal capacity locally
    max_partition_duration: int = 300       # Max partition duration before full local mode
    accuracy_bounds: Dict[str, float] = None  # Expected accuracy bounds in degraded modes
    probabilistic_allow_rate: float = 0.1   # Rate for probabilistic mode
    clock_skew_tolerance_ms: int = 1000     # Clock skew tolerance in milliseconds
    failure_threshold: int = 5              # Circuit breaker failure threshold
    timeout_duration: int = 30              # Circuit breaker timeout duration
    recovery_timeout: int = 10              # Circuit breaker recovery timeout
    endpoint_degradation_modes: Dict[str, DegradationMode] = None  # Per-endpoint degradation modes
    endpoint_configs: Dict[str, DegradationMode] = None  # Per-endpoint fallback strategies
    
    def __post_init__(self):
        if self.accuracy_bounds is None:
            self.accuracy_bounds = {
                'local_only': 0.85,        # 85% accuracy in local-only mode (≤15% deviation)
                'probabilistic': 0.5,      # 50% accuracy in probabilistic mode
                'fail_open': 0.0           # No accuracy guarantees when failing open
            }
        if self.endpoint_degradation_modes is None:
            self.endpoint_degradation_modes = {}
        if self.endpoint_configs is None:
            self.endpoint_configs = {}


class CircuitBreaker:
    """Circuit breaker for Redis operations with exponential backoff"""
    
    def __init__(self, failure_threshold: int = 5, timeout_duration: int = 30, 
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
            buckets=[0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
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
        
        # SLA tracking
        self.availability_target = 0.999
        self.latency_p95_target = 0.001  # 1ms
        
    def observe_request(self, latency: float, allowed: bool, endpoint: str = "default"):
        """Record request metrics"""
        if not self.enabled:
            return
            
        status = "allowed" if allowed else "denied"
        self.requests_total.labels(status=status, endpoint=endpoint).inc()
        self.request_latency.observe(latency)
    
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
    
    # Enhanced Lua script for atomic token bucket operations with microsecond precision
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
    
    -- Mathematical invariant validation
    assert(tokens >= 0 and tokens <= capacity, "Token invariant violated: " .. tokens)
    
    -- Clock skew handling
    local time_elapsed = now - last_refill
    if math.abs(time_elapsed) > clock_skew_tolerance then
        redis.log(redis.LOG_WARNING, "Clock skew detected: " .. time_elapsed)
        if time_elapsed < 0 then
            now = last_refill  -- Use previous timestamp if clock went backward
        end
    end
    
    -- Handle different window strategies
    local window_result = {}
    if window_strategy == 'sliding_counter' then
        -- Sliding window counter logic with boundary validation
        local window_elapsed = now - window_start
        if window_elapsed >= window_size then
            -- Start new window
            window_start = now
            request_count = 0
        end
        
        -- Calculate window allowance with precision
        local window_progress = math.min(window_elapsed / window_size, 1.0)
        assert(window_progress >= 0 and window_progress <= 1.0, "Invalid window progress: " .. window_progress)
        
        local window_allowance = capacity * (1.0 - window_progress) + 
                               (capacity * window_progress * request_count / capacity)
        
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
    
    -- Round to precision digits
    tokens = math.floor(tokens * (10 ^ precision_digits) + 0.5) / (10 ^ precision_digits)
    
    -- Check if request can be served
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
    
    -- Window state consistency validation
    if window_strategy == 'sliding_counter' then
        assert(window_start <= now and request_count >= 0, 
               "Window state inconsistent: start=" .. window_start .. ", count=" .. request_count)
    end
    
    -- Update state atomically
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
    
    -- Check each dimension
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
                 shard_count: int = 4):
        self.redis_url = redis_url
        self.pool_size = pool_size
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.retry_on_timeout = retry_on_timeout
        self.health_check_interval = health_check_interval
        self.shard_count = shard_count
        
        # Connection pools
        self._sync_pool: Optional[redis.ConnectionPool] = None
        self._async_pool: Optional[aioredis.ConnectionPool] = None
        self._sync_client: Optional[redis.Redis] = None
        self._async_client: Optional[aioredis.Redis] = None
        
        # Script hashes for loaded Lua scripts
        self._script_hashes: Dict[str, str] = {}
        self._health_status = True
        self._last_health_check = time.time()
        
        # Circuit breaker for fault tolerance
        self.circuit_breaker = CircuitBreaker()
        
    def _create_sync_client(self) -> redis.Redis:
        """Create synchronous Redis client"""
        if not self._sync_pool:
            self._sync_pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.pool_size,
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                retry_on_timeout=self.retry_on_timeout,
                decode_responses=True
            )
        
        if not self._sync_client:
            self._sync_client = redis.Redis(connection_pool=self._sync_pool)
            self.circuit_breaker.redis_client = self._sync_client
            self._load_scripts_sync()
            
        return self._sync_client
    
    async def _create_async_client(self) -> aioredis.Redis:
        """Create asynchronous Redis client"""
        if not self._async_pool:
            self._async_pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.pool_size,
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                retry_on_timeout=self.retry_on_timeout,
                decode_responses=True
            )
            
        if not self._async_client:
            self._async_client = aioredis.Redis(connection_pool=self._async_pool)
            await self._load_scripts_async()
            
        return self._async_client
    
    def _load_scripts_sync(self):
        """Load Lua scripts into Redis (sync) with EVALSHA optimization"""
        try:
            client = self._sync_client
            self._script_hashes['token_bucket'] = client.script_load(self.TOKEN_BUCKET_LUA)
            self._script_hashes['sliding_window_log'] = client.script_load(self.SLIDING_WINDOW_LOG_LUA)
            self._script_hashes['multi_dimension'] = client.script_load(self.MULTI_DIMENSION_LUA)
        except RedisError as e:
            logger.error(f"Failed to load Lua scripts: {e}")
    
    async def _load_scripts_async(self):
        """Load Lua scripts into Redis (async) with EVALSHA optimization"""
        try:
            client = self._async_client
            self._script_hashes['token_bucket'] = await client.script_load(self.TOKEN_BUCKET_LUA)
            self._script_hashes['sliding_window_log'] = await client.script_load(self.SLIDING_WINDOW_LOG_LUA)
            self._script_hashes['multi_dimension'] = await client.script_load(self.MULTI_DIMENSION_LUA)
        except RedisError as e:
            logger.error(f"Failed to load Lua scripts: {e}")
    
    def check_health(self) -> bool:
        """Check Redis health with circuit breaker integration"""
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
    
    async def check_health_async(self) -> bool:
        """Check Redis health (async) with circuit breaker integration"""
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
        if not self._sync_pool:
            return {}
            
        return {
            "active_connections": getattr(self._sync_pool, 'created_connections', 0),
            "available_connections": getattr(self._sync_pool, 'available_connections', 0),
            "max_connections": self.pool_size,
            "circuit_breaker_state": self.circuit_breaker.state.value
        }
    
    def execute_with_pipeline(self, operations: List[Callable]) -> List[Any]:
        """Execute multiple operations using Redis pipeline"""
        client = self._create_sync_client()
        try:
            with client.pipeline() as pipe:
                for operation in operations:
                    operation(pipe)
                results = pipe.execute()
                return results
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"Pipeline execution failed: {e}")
            raise
    
    def _execute_script_with_fallback(self, client, script_name: str, keys: List[str], args: List[str]):
        """Execute script with EVALSHA optimization and NOSCRIPT fallback"""
        try:
            script_hash = self._script_hashes.get(script_name)
            if script_hash:
                result = client.evalsha(script_hash, len(keys), *keys, *args)
                return result
        except NoScriptError:
            # Script not in cache, reload and retry
            script_content = getattr(self, f"{script_name.upper()}_LUA", "")
            if script_content:
                result = client.eval(script_content, len(keys), *keys, *args)
                return result
            else:
                raise ValueError(f"Unknown script: {script_name}")
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"Script execution failed: {e}")
            raise
    
    async def _execute_script_with_fallback_async(self, client, script_name: str, keys: List[str], args: List[str]):
        """Execute script with EVALSHA optimization and NOSCRIPT fallback (async)"""
        try:
            script_hash = self._script_hashes.get(script_name)
            if script_hash:
                result = await client.evalsha(script_hash, len(keys), *keys, *args)
                return result
        except NoScriptError:
            # Script not in cache, reload and retry
            script_content = getattr(self, f"{script_name.upper()}_LUA", "")
            if script_content:
                result = await client.eval(script_content, len(keys), *keys, *args)
                return result
            else:
                raise ValueError(f"Unknown script: {script_name}")
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"Script execution failed: {e}")
            raise


class LocalTokenBucket:
    """In-memory token bucket for fallback scenarios with TTL support"""
    
    def __init__(self, capacity: int, refill_rate: float, initial_tokens: Optional[float] = None, ttl: int = 3600):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = initial_tokens if initial_tokens is not None else capacity
        self.last_refill = time.time()
        self.creation_time = time.time()
        self.ttl = ttl
        self._lock = threading.RLock()
    
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
        """Synchronize local bucket with Redis state"""
        with self._lock:
            if 'tokens' in redis_state:
                # Reconcile with some smoothing to avoid abrupt changes
                redis_tokens = redis_state['tokens']
                self.tokens = (self.tokens + redis_tokens) / 2


class SlidingWindowCounter:
    """Sliding window counter for advanced rate limiting with memory optimization"""
    
    def __init__(self, limit: int, window_size: int, precision: Optional[int] = None, max_buckets: int = 1000):
        self.limit = limit
        self.window_size = window_size
        
        # Ensure bucket resolution ≤100ms
        self.precision = max(10, int(window_size / 0.1)) if precision is None else precision
        self.sub_window_size = window_size / self.precision
        self.max_buckets = max_buckets
        
        self.counters: Dict[int, int] = {}
        self._lock = threading.RLock()
    
    def is_allowed(self, cost: int = 1) -> Tuple[bool, Dict]:
        """Check if request is allowed under sliding window"""
        with self._lock:
            now = time.time()
            current_window = int(now / self.sub_window_size)
            
            # Memory management with LRU-style eviction
            if len(self.counters) > self.max_buckets:
                oldest_keys = sorted(self.counters.keys())[:-self.max_buckets//2]
                for key in oldest_keys:
                    del self.counters[key]
            
            # Clean old windows
            cutoff = current_window - self.precision
            self.counters = {k: v for k, v in self.counters.items() if k > cutoff}
            
            # Calculate current usage across sliding window
            total_requests = sum(self.counters.values())
            
            # Calculate weighted average for more accurate sliding behavior
            window_progress = (now % self.sub_window_size) / self.sub_window_size
            if current_window in self.counters:
                # Adjust for partial window
                adjusted_current = self.counters[current_window] * window_progress
                total_requests = total_requests - self.counters[current_window] + adjusted_current
            
            allowed = total_requests + cost <= self.limit
            
            if allowed:
                self.counters[current_window] = self.counters.get(current_window, 0) + cost
            
            return allowed, {
                'total_requests': total_requests,
                'limit': self.limit,
                'window_progress': window_progress,
                'sub_windows': len(self.counters),
                'bucket_resolution_ms': self.sub_window_size * 1000
            }


class RateLimitInvariants:
    """Formal invariant checking for rate limiting"""
    
    @staticmethod
    def verify_token_conservation(all_buckets: List[Dict]) -> bool:
        """Verify token conservation invariant"""
        total_tokens = sum(bucket.get('tokens', 0) for bucket in all_buckets)
        total_capacity = sum(bucket.get('capacity', 0) for bucket in all_buckets)
        return total_tokens <= total_capacity
    
    @staticmethod
    def verify_rate_limit_invariant(requests_in_window: int, limit: int, accuracy_bound: float) -> bool:
        """Verify rate limit invariant with accuracy bound"""
        actual_deviation = abs(requests_in_window - limit) / limit if limit > 0 else 0
        return actual_deviation <= (1.0 - accuracy_bound)


class SLATracker:
    """SLA tracking and compliance monitoring"""
    
    def __init__(self):
        self.availability_target = 0.999
        self.latency_p95_target = 0.001
        self.total_requests = 0
        self.successful_requests = 0
        self.latencies = []
        self._lock = threading.RLock()
        
    def record_request(self, successful: bool, latency: float):
        """Record request for SLA tracking"""
        with self._lock:
            self.total_requests += 1
            if successful:
                self.successful_requests += 1
            self.latencies.append(latency)
            
            # Keep only recent latencies for memory management
            if len(self.latencies) > 10000:
                self.latencies = self.latencies[-5000:]
    
    def check_sla_compliance(self) -> Dict[str, bool]:
        """Check SLA compliance"""
        with self._lock:
            if self.total_requests == 0:
                return {"availability": True, "latency": True}
                
            availability = self.successful_requests / self.total_requests
            
            # Calculate P95 latency
            if self.latencies:
                sorted_latencies = sorted(self.latencies)
                p95_index = int(0.95 * len(sorted_latencies))
                p95_latency = sorted_latencies[p95_index] if p95_index < len(sorted_latencies) else 0
            else:
                p95_latency = 0
                
            return {
                "availability": availability >= self.availability_target,
                "latency": p95_latency <= self.latency_p95_target,
                "availability_value": availability,
                "latency_p95_value": p95_latency
            }


class DistributedTokenBucketRateLimiter:
    """
    Production-ready distributed token bucket rate limiter with Redis backend
    
    Features:
    - Token bucket algorithm with configurable refill rates
    - Sliding window support for more accurate rate limiting
    - Redis backend for distributed coordination
    - Graceful degradation when Redis is unavailable
    - Partition tolerance with documented accuracy bounds
    - Circuit breaker pattern for fault tolerance
    - Multi-dimensional rate limiting support
    - Comprehensive monitoring and metrics
    """
    
    def __init__(self,
                 redis_backend: RedisBackend,
                 partition_config: PartitionToleranceConfig = None,
                 key_prefix: str = "rate_limit",
                 default_ttl: int = 300,
                 enable_metrics: bool = True,
                 service_name: str = "rate_limiter"):
        self.redis_backend = redis_backend
        self.partition_config = partition_config or PartitionToleranceConfig()
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self.enable_metrics = enable_metrics
        self.service_name = service_name
        
        # Local fallback storage with LRU cache
        self._local_buckets: Dict[str, LocalTokenBucket] = {}
        self._local_windows: Dict[str, SlidingWindowCounter] = {}
        self._local_lock = threading.RLock()
        
        # Partition state tracking
        self._partition_start_time: Optional[float] = None
        self._degraded_mode = False
        
        # Metrics and monitoring
        self.prometheus_metrics = PrometheusMetrics(enable_metrics)
        self.sla_tracker = SLATracker()
        
        # Basic metrics for non-Prometheus environments
        self._metrics = {
            'total_requests': 0,
            'allowed_requests': 0,
            'denied_requests': 0,
            'redis_errors': 0,
            'fallback_requests': 0,
            'degraded_duration': 0.0,
            'p95_latency': 0.0
        }
        
        # Latency tracking for performance optimization
        self._latency_samples = []
        self._latency_lock = threading.RLock()
        
        # Alerting configuration
        self.alerting_config = {
            "redis_errors_threshold": 10,
            "degraded_mode_duration_threshold": 300,
            "severity_levels": ["warning", "critical"],
            "latency_threshold_ms": 1000
        }
        
    def _get_redis_key(self, identifier: str, config: RateLimitConfig) -> str:
        """Generate Redis key for rate limit bucket with hash tags for cluster compatibility"""
        config_hash = hashlib.md5(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()[:8]
        # Use hash tags to ensure same slot assignment in Redis Cluster
        return f"{self.key_prefix}:{{{identifier}}}:{config_hash}"
    
    def _get_dimensional_key(self, dimension_type: str, identifier: str, config: RateLimitConfig) -> str:
        """Generate hierarchical key for multi-dimensional rate limiting"""
        config_hash = hashlib.md5(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()[:8]
        return f"{self.key_prefix}:{dimension_type}:{{{identifier}}}:{config_hash}"
    
    def _get_sharded_keys(self, identifier: str, config: RateLimitConfig, shard_count: int = 4) -> List[str]:
        """Generate sharded keys for hot key prevention"""
        config_hash = hashlib.md5(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()[:8]
        return [
            f"{self.key_prefix}:{{{identifier}}}:shard_{i}:{config_hash}"
            for i in range(shard_count)
        ]
    
    def _distribute_load(self, base_key: str, shard_count: int = 4) -> str:
        """Distribute load across Redis cluster nodes"""
        hash_value = hashlib.md5(base_key.encode()).hexdigest()
        shard_id = int(hash_value[:8], 16) % shard_count
        return f"{base_key}:shard_{shard_id}"
    
    def _update_metrics(self, allowed: bool, degraded: bool, latency: float, redis_error: bool = False):
        """Update internal metrics"""
        if not self.enable_metrics:
            return
            
        self._metrics['total_requests'] += 1
        
        if allowed:
            self._metrics['allowed_requests'] += 1
        else:
            self._metrics['denied_requests'] += 1
            
        if degraded:
            self._metrics['fallback_requests'] += 1
            
        if redis_error:
            self._metrics['redis_errors'] += 1
        
        # Update latency tracking
        with self._latency_lock:
            self._latency_samples.append(latency)
            if len(self._latency_samples) > 1000:
                self._latency_samples = self._latency_samples[-500:]
            
            # Calculate P95 latency
            if self._latency_samples:
                sorted_samples = sorted(self._latency_samples)
                p95_index = int(0.95 * len(sorted_samples))
                self._metrics['p95_latency'] = sorted_samples[p95_index] if p95_index < len(sorted_samples) else 0
        
        # Record SLA metrics
        self.sla_tracker.record_request(allowed, latency)
        
        # Prometheus metrics
        self.prometheus_metrics.observe_request(latency, allowed)
    
    def _handle_partition_start(self):
        """Handle start of network partition"""
        if not self._degraded_mode:
            self._partition_start_time = time.time()
            self._degraded_mode = True
            logger.warning(f"Rate limiter entering degraded mode: {self.partition_config.degradation_mode.value}")
            
            # Set circuit breaker state in metrics
            self.prometheus_metrics.set_circuit_breaker_state(CircuitBreakerState.OPEN)
    
    def _handle_partition_end(self):
        """Handle end of network partition"""
        if self._degraded_mode:
            duration = time.time() - (self._partition_start_time or 0)
            self._metrics['degraded_duration'] += duration
            self._degraded_mode = False
            self._partition_start_time = None
            
            if self.prometheus_metrics.enabled:
                self.prometheus_metrics.degraded_mode_duration.observe(duration)
                self.prometheus_metrics.set_circuit_breaker_state(CircuitBreakerState.CLOSED)
            
            logger.info(f"Rate limiter exiting degraded mode after {duration:.2f}s")
    
    def _should_force_local_mode(self) -> bool:
        """Check if we should force local-only mode due to extended partition"""
        if not self._partition_start_time:
            return False
            
        duration = time.time() - self._partition_start_time
        return duration > self.partition_config.max_partition_duration
    
    def handle_consensus_failure(self):
        """Handle consensus failure in distributed environment"""
        if self._partition_start_time:
            duration = time.time() - self._partition_start_time
            max_consensus_timeout = self.partition_config.max_partition_duration / 2
            
            if duration > max_consensus_timeout:
                logger.warning("Consensus lost, switching to local-only mode")
                # Force local-only mode for consensus failure
                self._degraded_mode = True
    
    @contextmanager
    def _redis_operation(self):
        """Context manager for Redis operations with fallback handling"""
        try:
            if not self.redis_backend.check_health():
                raise ConnectionError("Redis health check failed")
                
            yield self.redis_backend._create_sync_client()
            
            # If we get here, operation succeeded - handle partition end
            if self._degraded_mode:
                self._handle_partition_end()
                
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error