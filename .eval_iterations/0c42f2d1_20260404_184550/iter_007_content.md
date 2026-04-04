## Overview

This walkthrough addresses intermittent 500 errors caused by race conditions in PostgreSQL connection pools under high concurrent load. We'll systematically identify, isolate, and resolve these issues while maintaining production safety.

## 1. Initial Problem Assessment

### Step 1.1: Confirm Race Condition Symptoms

Check your application logs for these specific error patterns:

```bash
# Look for these error messages indicating pool exhaustion
grep -E "(timeout exceeded when trying to connect|connection terminated|pool exhausted)" app.log
```

**Hypothesis 1: Pool exhaustion due to connection leaks.** Test: Monitor pool.idleCount over time. Expected: Decreasing idle connections without corresponding release events in logs.

**Hypothesis 2: Race condition in connection allocation timing.** Test: Correlate connection acquisition timestamps with pool waitingCount spikes. Expected: Multiple requests acquiring connections simultaneously during brief unavailability periods.

Key indicators of race conditions:
- Connection leaks where clients aren't properly released back to the pool
- Connection timeouts due to race conditions between timeout handlers and connection establishment
- Pool sometimes terminating idle connections that have just been checked out

**Async Race Condition Patterns:** 
Monitoring does not introduce any blocking beyond that present in repeatable read, but there is some overhead to the monitoring, and detection of the conditions which could cause a serialization anomaly will trigger a serialization failure.
 Event loop blocking occurs when synchronous operations in async handlers prevent other operations from proceeding. Common patterns that create race conditions include:

```javascript
// ❌ Event loop blocking pattern that causes race conditions
async function badAsyncPattern(userIds) {
  for (const id of userIds) {
    // This blocks event loop - each await prevents concurrent processing
    await pool.query('SELECT * FROM users WHERE id = $1', [id]);
  }
}

// ✅ Non-blocking pattern
async function goodAsyncPattern(userIds) {
  // Parallel execution prevents event loop blocking
  await Promise.all(userIds.map(id => 
    pool.query('SELECT * FROM users WHERE id = $1', [id])
  ));
}
```

**Shared State Race Conditions:** Global variables and shared state between requests create race conditions:

```javascript
// ❌ DANGEROUS - race condition between requests
let globalCounter = 0;

function unsafeIncrement() {
  // Race condition: read-modify-write not atomic between requests
  const current = globalCounter;
  setTimeout(() => {
    globalCounter = current + 1; // Another request could have modified this
  }, 1);
}

// ✅ Better: Use request-scoped state
app.use((req, res, next) => {
  req.requestCounter = Date.now(); // Request-scoped
  next();
});
```

**Atomic Database Operations:** Race conditions occur when partial database updates create inconsistent states. Use explicit transaction boundaries with atomic commit/rollback patterns:

```javascript
// ✅ Atomic operation pattern
async function atomicUserUpdate(userId, changes) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    
    // Atomic read-modify-write
    const user = await client.query('SELECT * FROM users WHERE id = $1 FOR UPDATE', [userId]);
    const updatedUser = { ...user.rows[0], ...changes };
    await client.query('UPDATE users SET data = $1 WHERE id = $2', [updatedUser, userId]);
    
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
```

### Step 1.2: Gather Pool Metrics

Monitor your current pool state using these metrics:

```javascript
// Add to your existing Express routes
app.get('/debug/pool-stats', (req, res) => {
  const utilizationPercent = Math.round(((pool.totalCount - pool.idleCount) / pool.totalCount) * 100);
  
  // Alert on specific thresholds
  if (utilizationPercent > 80) {
    console.warn('Pool utilization >80%:', { utilization: utilizationPercent });
  }
  
  if (pool.waitingCount > 10) {
    console.warn('High queue depth detected:', pool.waitingCount);
  }
  
  res.json({
    totalCount: pool.totalCount,     // Total connections
    idleCount: pool.idleCount,       // Available connections
    waitingCount: pool.waitingCount, // Queued requests
    utilizationPercent,
    timestamp: new Date().toISOString()
  });
});
```

**Production Safety Note**: The health endpoint exposes pool statistics that are useful for monitoring and alerting. Regular health checks ensure your application detects database connectivity issues early. The HTTP health check uses existing internal state to answer requests and doesn't send queries to the connection pools.

### Step 1.3: Add Production-Safe Debugging Tools

For production environments, use tools with minimal overhead:

```javascript
// Production-safe profiling with clinic.js
if (process.env.NODE_ENV === 'production') {
  // Clinic.js doctor adds <2% CPU overhead. Monitor production impact: 
  // if CPU usage increases >5% during profiling, reduce sampling rate.
  // clinic doctor -- node.js
  // Avoid --inspect in production due to security and performance risks
}

// Adjust sampling rate based on load: reduce overhead during high load
const cpuUsage = process.cpuUsage().user / 1000000; // Convert to seconds
const samplingRate = cpuUsage > 0.8 ? 0.0001 : 0.001;
const shouldSample = Math.random() < samplingRate;

if (shouldSample && req.headers['x-debug-enabled']) {
  req.enableTracing = true;
}
```

**Race condition confirmed when >5% of requests return 500 errors or when response time P95 exceeds 1000ms during concurrent load test.**

### Step 1.4: Create Reproducible Load Test

Use artillery to generate 50 concurrent requests over 10 seconds to enable consistent reproduction:

```bash
# Install and run artillery for load testing
npm install -g artillery
artillery quick --count 50 --num 10 http://localhost:3000/users/1

# Or use detailed configuration
cat > load-test.yml << EOF
config:
  target: 'http://localhost:3000'
  phases:
    - duration: 10
      arrivalRate: 50
scenarios:
  - name: "Concurrent user lookup"
    requests:
      - get:
          url: "/users/1"
EOF

artillery run load-test.yml
```

Match production database max_connections=100, network latency simulation with tc (traffic control), and similar CPU/memory constraints to ensure race conditions reproduce consistently:

```bash
# Simulate network latency (requires sudo)
sudo tc qdisc add dev lo root handle 1: prio
sudo tc qdisc add dev lo parent 1:3 handle 30: netem delay 5ms

# Clean up after testing
sudo tc qdisc del dev lo root
```

## 2. Database-Level Investigation

### Step 2.1: Monitor Active Connections

Monitor active and idle connections closely using this query:

```sql
-- Check for connection leaks and suspicious states
SELECT 
    pid,
    usename,
    application_name,
    client_addr,
    state,
    NOW() - backend_start AS connection_age,
    NOW() - query_start AS query_duration,
    query
FROM pg_stat_activity 
WHERE datname = 'your_database_name'
    AND state != 'idle'
ORDER BY connection_age DESC;
```

### Step 2.2: Analyze PostgreSQL Connection Overhead

Each PostgreSQL connection consumes ~10MB RAM (work_mem + connection overhead). Monitor with pg_stat_activity for connection count vs available memory:

```sql
-- Calculate memory usage per connection with complete analysis
SELECT 
    COUNT(*) as active_connections,
    COUNT(*) * 10 as estimated_memory_mb,
    AVG(EXTRACT(EPOCH FROM NOW() - backend_start)) as avg_age_seconds,
    -- Work memory impact per connection
    current_setting('work_mem')::int / 1024 as work_mem_mb_per_conn,
    -- Shared buffers allocated per connection estimate
    (current_setting('shared_buffers')::text::bigint / 1024 / 1024) as shared_buffers_mb,
    -- Total memory footprint estimation
    COUNT(*) * (10 + current_setting('work_mem')::int / 1024 / 1024) as total_memory_footprint_mb
FROM pg_stat_activity 
WHERE state IN ('active', 'idle in transaction', 'idle in transaction (aborted)');
```

PostgreSQL max_connections limited by RAM: (RAM_GB * 1024 - shared_buffers) / 10MB_per_connection. Typical production: 100-200 connections.

### Step 2.3: Identify Problematic Connection Patterns

Look for connections that timeout during establishment but maintain idle connections on the PostgreSQL side:

```sql
-- Find potentially leaked connections
SELECT * FROM pg_stat_activity 
WHERE query_start IS NULL 
    AND state = 'idle'
    AND backend_start < NOW() - INTERVAL '5 minutes';
```

Monitor for "idle in transaction" states which can hold locks and affect performance:

```sql
-- Critical: Find long-running idle transactions
SELECT 
    pid,
    usename,
    application_name,
    NOW() - xact_start AS txn_duration,
    state,
    query
FROM pg_stat_activity 
WHERE state = 'idle in transaction'
    AND NOW() - xact_start > INTERVAL '30 seconds'
ORDER BY txn_duration DESC;
```

### Step 2.4: PostgreSQL Server Connection Lifecycle

PostgreSQL creates backend process per connection. Monitor backend_start in pg_stat_activity. Connections in idle state consume minimal CPU but hold memory.

### Step 2.5: PostgreSQL Query Cancellation Race Conditions

Monitor for query cancellation race conditions where cancel requests can target the wrong query due to timing issues between connection reuse and cancellation signals:

```sql
-- Track cancellation race conditions by monitoring connection reuse patterns
SELECT 
    pid,
    application_name,
    backend_start,
    query_start,
    state,
    query,
    -- Detect rapid connection reuse that can cause cancellation race conditions
    CASE WHEN backend_start > NOW() - INTERVAL '10 seconds' 
         AND state = 'active' 
         THEN 'potential_cancel_race_condition' 
         ELSE 'normal' END as race_condition_risk
FROM pg_stat_activity 
WHERE datname = 'your_database_name'
    AND application_name LIKE '%nodejs-app%'
ORDER BY backend_start DESC;
```

Implement per-connection cancellation tracking to prevent cross-query interference by doubly-linking cancel requests and the original server connection:

```javascript
// Track active query per connection to prevent cancellation race conditions
const connectionQueryMap = new Map();

class SafeCancellationTracker {
  constructor(pool) {
    this.pool = pool;
    this.activeQueries = new Map(); // Track queryId -> connection mapping
  }
  
  async executeWithCancellationSafety(client, sql, params, queryId) {
    // Associate this query with its connection
    this.activeQueries.set(queryId, {
      client,
      startTime: Date.now(),
      sql: sql.substring(0, 100) // First 100 chars for logging
    });
    
    // Implement timeout-based cancellation with proper isolation
    const timeoutId = setTimeout(() => {
      const queryInfo = this.activeQueries.get(queryId);
      if (queryInfo && queryInfo.client === client) {
        console.warn('Query timeout, canceling:', { queryId, sql: queryInfo.sql });
        client.cancel();
      }
    }, 30000);
    
    try {
      const result = await client.query(sql, params);
      return result;
    } finally {
      clearTimeout(timeoutId);
      this.activeQueries.delete(queryId);
    }
  }
  
  // Safe cancellation that only affects the intended query
  safeCancelQuery(queryId) {
    const queryInfo = this.activeQueries.get(queryId);
    if (queryInfo) {
      console.log('Canceling specific query:', queryId);
      queryInfo.client.cancel();
      this.activeQueries.delete(queryId);
    } else {
      console.warn('Query not found for cancellation:', queryId);
    }
  }
}
```

## 3. Application Code Review

### Step 3.1: Audit Connection Release Patterns

Review your Express middleware for proper connection handling:

```javascript
// ✅ CORRECT - Race condition resistant
app.get('/users/:id', async (req, res) => {
  let client;
  
  try {
    client = await pool.connect();
    const result = await client.query('SELECT * FROM users WHERE id = $1', [req.params.id]);
    res.json(result.rows[0]);
  } catch (error) {
    console.error('Database error:', error);
    res.status(500).json({ error: 'Internal server error' });
  } finally {
    if (client) {
      client.release();
    }
  }
});
```

### Step 3.2: Detect Shared Connection Anti-patterns

Avoid sharing connections between concurrent requests:

```javascript
// ✅ CORRECT - Request-scoped connections
app.use(async (req, res, next) => {
  req.getDbConnection = async () => {
    return await pool.connect(); // Each request gets its own connection
  };
  next();
});
```

### Step 3.3: Implement Circuit Breaker for Database Resilience

Add circuit breaker implementation with failure thresholds: if (failureRate > 0.5 && failures > 10) { return cachedResponse; } with timeout windows:

```javascript
const CircuitBreaker = require('opossum');

// Circuit breaker configuration for database operations
const dbCircuitOptions = {
  timeout: 5000,                    // 5 second timeout
  errorThresholdPercentage: 50,     // Trip when 50% of requests fail
  resetTimeout: 30000,              // Try again after 30 seconds
  rollingCountTimeout: 10000,       // 10 second rolling window
  rollingCountBuckets: 10,          // Granular monitoring
  volumeThreshold: 10               // Minimum requests before tripping
};

const dbCircuit = new CircuitBreaker(executeQuery, dbCircuitOptions);

// Enhanced fallback strategy for graceful degradation
dbCircuit.fallback(() => {
  return { 
    data: getCachedData(), 
    source: 'cache', 
    degraded: true,
    message: 'Service operating in degraded mode with cached data'
  };
});

// Circuit breaker monitoring and metrics
dbCircuit.on('open', () => console.warn('Circuit breaker OPEN - failing fast'));
dbCircuit.on('halfOpen', () => console.info('Circuit breaker HALF-OPEN - testing'));
dbCircuit.on('close', () => console.info('Circuit breaker CLOSED - operating normally'));

async function executeQuery(sql, params) {
  const client = await pool.connect();
  try {
    return await client.query(sql, params);
  } finally {
    client.release();
  }
}

// Use in routes with comprehensive fallback
app.get('/users/:id', async (req, res) => {
  try {
    const result = await dbCircuit.fire('SELECT * FROM users WHERE id = $1', [req.params.id]);
    
    if (result.degraded) {
      res.setHeader('X-Service-Mode', 'degraded');
      res.status(202); // Accepted but degraded
    }
    
    res.json(result);
  } catch (error) {
    res.status(503).json({ 
      error: 'Service temporarily unavailable',
      retryAfter: 30
    });
  }
});
```

### Step 3.4: Review Pool Configuration

Ensure your pool configuration prevents common race conditions:

```javascript
const { Pool } = require('pg');
const os = require('os');

// Calculate optimal pool sizes based on system resources
function calculateOptimalPoolSize() {
  const cpuCount = os.cpus().length;
  const maxDbConnections = parseInt(process.env.DB_MAX_CONNECTIONS) || 100;
  const appInstances = parseInt(process.env.APP_INSTANCES) || 1;
  const reservedConnections = 10; // For admin/monitoring
  
  // PostgreSQL formula: (cores * 2) + 1
  const formulaMax = (cpuCount * 2) + 1;
  
  // Fair share calculation
  const availableConnections = maxDbConnections - reservedConnections;
  const fairShare = Math.floor(availableConnections / appInstances);
  
  // Use the lower of formula result and fair share
  const recommendedMax = Math.min(formulaMax, fairShare);
  
  return {
    max: recommendedMax,
    min: Math.max(2, Math.floor(recommendedMax * 0.1))
  };
}

const poolSize = calculateOptimalPoolSize();

const pool = new Pool({
  // Database connection
  host: process.env.DB_HOST,
  port: parseInt(process.env.DB_PORT) || 5432,
  database: process.env.DB_NAME,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  
  // Calculated pool sizing - Critical for preventing exhaustion
  max: poolSize.max,                  // Total connections
  min: poolSize.min,                  // Minimum idle connections
  
  // Timeout configuration - Prevents hanging connections
  idleTimeoutMillis: 30000,           // Close idle connections after 30s
  connectionTimeoutMillis: 5000,      // Fail fast if pool exhausted
  
  // Query timeout - Prevents runaway queries
  statement_timeout: 30000,           // Kill queries > 30s
  query_timeout: 30000,
  
  // Application identification for debugging
  application_name: process.env.APP_NAME || 'nodejs-app',
  
  // Keep connections alive
  allowExitOnIdle: false,
  
  // Prevent race conditions with connection setup
  onConnect: async (client) => {
    // This ensures setup completes before connection is available
    await client.query("SET search_path TO app_schema, public");
    await client.query("SET application_name TO $1", [process.env.APP_NAME]);
  }
});
```

### Step 3.5: Implement Express Error Middleware

Add Express error middleware: app.use((err, req, res, next) => { if (err.code === 'ECONNREFUSED') res.status(503); else res.status(500); res.json({error: err.message}); }):

```javascript
// Centralized error handling middleware
app.use((err, req, res, next) => {
  console.error('Error:', err);
  
  // Classify error types for proper HTTP status codes
  if (err.code === 'ECONNREFUSED' || err.code === 'ENOTFOUND') {
    res.status(503).json({ error: 'Database unavailable' });
  } else if (err.code === '40001' || err.code === '40P01') {
    res.status(409).json({ error: 'Transaction conflict, please retry' });
  } else if (err.message?.includes('pool exhausted')) {
    res.status(503).json({ error: 'Service overloaded' });
  } else {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Process-level error handlers for uncaught async errors
process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
  // Log to error tracking service
  process.exit(1);
});

process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception:', error);
  process.exit(1);
});
```

## 4. Advanced Race Condition Detection

### Step 4.1: Add Connection Lifecycle Logging

Monitor pool events to detect race conditions:

```javascript
// Add comprehensive pool event logging
pool.on('connect', (client) => {
  console.log(`Pool: New connection created. Total: ${pool.totalCount}`);
});

pool.on('acquire', (client) => {
  console.log(`Pool: Connection acquired. Available: ${pool.idleCount}`);
});

pool.on('release', (client) => {
  console.log(`Pool: Connection released. Available: ${pool.idleCount}`);
});

pool.on('remove', (client) => {
  console.log(`Pool: Connection removed. Total: ${pool.totalCount}`);
});

pool.on('error', (err, client) => {
  console.error('Pool: Unexpected error on idle client', err);
  // Critical: Report to error tracking service
});
```

### Step 4.2: Implement Connection Tracking

Create a connection wrapper to detect leaks:

```javascript
class ConnectionTracker {
  constructor() {
    this.activeConnections = new Map();
  }
  
  async getConnection(requestId) {
    const client = await pool.connect();
    const connectionInfo = {
      id: requestId,
      acquiredAt: new Date(),
      stack: new Error().stack // For debugging leaks
    };
    
    this.activeConnections.set(client, connectionInfo);
    
    // Wrap release method to track cleanup
    const originalRelease = client.release.bind(client);
    client.release = () => {
      this.activeConnections.delete(client);
      originalRelease();
    };
    
    return client;
  }
  
  // Call this periodically to detect leaks
  checkForLeaks() {
    const now = new Date();
    for (const [client, info] of this.activeConnections) {
      const age = now - info.acquiredAt;
      if (age > 60000) { // 1 minute
        console.warn(`Potential connection leak detected:`, {
          requestId: info.id,
          age: age,
          stack: info.stack
        });
      }
    }
  }
  
  // Track memory growth patterns with heap profiling
  trackMemoryUsage() {
    const memUsage = process.memoryUsage();
    const correlationRatio = memUsage.heapUsed / pool.totalCount;
    
    if (correlationRatio > 50 * 1024 * 1024) { // > 50MB per connection
      console.warn('High memory per connection detected:', {
        heapUsed: memUsage.heapUsed,
        totalConnections: pool.totalCount,
        ratioMB: correlationRatio / 1024 / 1024
      });
    }
    
    // Trigger heap snapshot on significant memory growth
    if (process.env.ENABLE_HEAP_PROFILING === 'true') {
      const heapdump = require('heapdump');
      if (memUsage.heapUsed > 500 * 1024 * 1024) {
        heapdump.writeSnapshot();
        console.log('Heap snapshot taken due to memory growth');
      }
    }
  }
}

const tracker = new ConnectionTracker();

// Use in middleware
app.use(async (req, res, next) => {
  req.getDbConnection = () => tracker.getConnection(req.headers['x-request-id'] || 'unknown');
  next();
});

// Periodic leak detection and memory tracking
setInterval(() => {
  tracker.checkForLeaks();
  tracker.trackMemoryUsage();
}, 30000);
```

### Step 4.3: Implement AsyncLocalStorage for Context Tracking

Add AsyncLocalStorage implementation: const asyncLocalStorage = new AsyncLocalStorage(); app.use((req, res, next) => { asyncLocalStorage.run(req.id, next); }):

```javascript
const { AsyncLocalStorage } = require('node:async_hooks');

const asyncLocalStorage = new AsyncLocalStorage();

// Middleware for context propagation
app.use((req, res, next) => {
  const context = {
    requestId: req.headers['x-request-id'] || require('crypto').randomUUID(),
    startTime: Date.now(),
    userId: req.user?.id
  };
  
  asyncLocalStorage.run(context, () => {
    req.context = context;
    next();
  });
});

// Enhanced structured logging with context and percentile tracking
const latencies = [];

function logDatabaseOperation(operation, duration, poolMetrics, queryDetails) {
  const context = asyncLocalStorage.getStore();
  
  // Track latencies for percentile calculation
  latencies.push(duration);
  if (latencies.length > 1000) {
    latencies.splice(0, 100); // Keep only recent measurements
  }
  
  // Calculate P95 latency target with specific thresholds
  if (latencies.length > 10) {
    const sortedLatencies = [...latencies].sort((a, b) => a - b);
    const p95 = sortedLatencies[Math.floor(sortedLatencies.length * 0.95)];
    const p99 = sortedLatencies[Math.floor(sortedLatencies.length * 0.99)];
    
    // SLI: 95% of database queries complete within 200ms, measured over 5-minute rolling windows
    if (p95 > 200) {
      console.warn('P95 latency SLI violation:', { p95, target: 200, p99 });
    }
  }
  
  // Complete structured logging format with all required fields
  console.log(JSON.stringify({
    timestamp: new Date().toISOString(),
    correlationId: context?.requestId,
    userId: context?.userId,
    operation,
    duration,
    query: queryDetails?.sql?.substring(0, 100),
    queryParams: queryDetails?.params?.length,
    poolSize: poolMetrics.totalCount,
    poolIdle: poolMetrics.idleCount,
    poolWaiting: poolMetrics.waitingCount,
    connectionAcquisitionTime: queryDetails?.connectionTime
  }));
}

// Use in database operations with comprehensive instrumentation
app.get('/users/:id', async (req, res) => {
  const start = Date.now();
  const connectionStart = Date.now();
  let client;
  
  try {
    client = await pool.connect();
    const connectionTime = Date.now() - connectionStart;
    
    const result = await client.query('SELECT * FROM users WHERE id = $1', [req.params.id]);
    
    logDatabaseOperation('SELECT users', Date.now() - start, {
      totalCount: pool.totalCount,
      idleCount: pool.idleCount,
      waitingCount: pool.waitingCount
    }, {
      sql: 'SELECT * FROM users WHERE id = $1',
      params: [req.params.id],
      connectionTime
    });
    
    res.json(result.rows[0]);
  } finally {
    if (client) client.release();
  }
});
```

### Step 4.4: Detect Event Loop Blocking

Add event loop monitoring with specific thresholds and pool correlation:

```javascript
const { performance } = require('perf_hooks');
const cluster = require('cluster');
const os = require('os');

// Event loop lag monitoring with specific implementation details
function monitorEventLoop() {
  const start = performance.hrtime.bigint();
  setImmediate(() => {
    const lag = Number(performance.hrtime.bigint() - start) / 1e6; // Convert to milliseconds
    
    // Specific 10ms threshold for event loop lag detection
    if (lag > 10) {
      console.warn('Event loop lag detected:', {
        lag: lag + 'ms',
        poolConnections: pool.totalCount,
        activeRequests: pool.waitingCount,
        poolUtilization: (pool.totalCount - pool.idleCount) / pool.totalCount
      });
    }
  });
}

setInterval(monitorEventLoop, 1000);

// Clustering implementation for CPU utilization
if (cluster.isMaster) {
  const numCPUs = os.cpus().length;
  console.log(`Master process ${process.pid} is running`);
  
  // Adjust pool size for clustering to prevent connection exhaustion
  const totalConnections = parseInt(process.env.DB_MAX_CONNECTIONS) || 100;
  const connectionsPerWorker = Math.floor(totalConnections / numCPUs);
  
  process.env.WORKER_POOL_SIZE = connectionsPerWorker.toString();
  
  // Fork workers with staggered startup to prevent connection storms
  for (let i = 0; i < numCPUs; i++) {
    setTimeout(() => {
      cluster.fork();
    }, i * 1000); // 1 second stagger between workers
  }
  
  cluster.on('exit', (worker, code, signal) => {
    console.log(`Worker ${worker.process.pid} died`);
    // Restart with delay to prevent rapid cycling
    setTimeout(() => cluster.fork(), 5000);
  });
  
  // Graceful shutdown handling
  process.on('SIGTERM', () => {
    console.log('Master received SIGTERM, shutting down workers...');
    for (const worker of Object.values(cluster.workers)) {
      worker.kill('SIGTERM');
    }
  });
  
} else {
  // Worker process with optimized pool configuration
  const poolSize = parseInt(process.env.WORKER_POOL_SIZE) || 10;
  
  const pool = new Pool({
    max: poolSize,
    min: Math.max(1, Math.floor(poolSize * 0.1)),
    // Worker-specific configuration
    application_name: `${process.env.APP_NAME}-worker-${process.pid}`,
    // ... other config
  });
  
  console.log(`Worker ${process.pid} started with pool size ${poolSize}`);
  startServer();
}

// Optimize async patterns to avoid await in loops - specific examples
async function processUsersInParallel(userIds, batchSize = 10) {
  // ❌ Inefficient - Sequential processing blocks event loop
  // for (const id of userIds) { await processUser(id); }
  
  // ✅ Efficient - Use Promise.all for parallel processing
  // Avoid: for(const id of ids) { await query(id); } Use: await Promise.all(ids.map(id => query(id)))
  const promises = userIds.map(async (id) => {
    const client = await pool.connect();
    try {
      const result = await client.query('SELECT * FROM users WHERE id = $1', [id]);
      return result.rows[0];
    } finally {
      client.release();
    }
  });
  
  // Use Promise.allSettled for partial failure tolerance
  const results = await Promise.allSettled(promises);
  return results
    .filter(result => result.status === 'fulfilled')
    .map(result => result.value);
}

// Traffic measurement for capacity planning
let requestCount = 0;
let queryCount = 0;
const startTime = Date.now();

// Monitor requests/second and database QPS for capacity planning. Track peak traffic patterns and growth trends.
app.use((req, res, next) => {
  requestCount++;
  
  // Calculate current RPS and QPS every minute
  if (requestCount % 100 === 0) {
    const elapsed = (Date.now() - startTime) / 1000;
    const rps = requestCount / elapsed;
    const qps = queryCount / elapsed;
    
    console.log('Traffic measurement:', {
      requestsPerSecond: rps.toFixed(2),
      queriesPerSecond: qps.toFixed(2),
      totalRequests: requestCount,
      totalQueries: queryCount,
      uptimeSeconds: elapsed
    });
  }
  
  next();
});

// Track database queries for QPS calculation
const originalQuery = pool.query;
pool.query = function(...args) {
  queryCount++;
  return originalQuery.apply(this, args);
};

// Detect shared variable mutations causing race conditions
const sharedVariableTracker = {
  connectionCount: 0,
  pendingQueries: new Set(),
  
  incrementConnection() {
    // ❌ Non-atomic operation - race condition prone
    this.connectionCount++;
  },
  
  safeIncrementConnection() {
    // ✅ Using atomic-like patterns
    const current = this.connectionCount;
    this.connectionCount = current + 1;
    return this.connectionCount;
  }
};
```

### Step 4.5: Detect Async Leak Patterns

Add async leak patterns: 'Common leaks: unclosed EventEmitter listeners, setTimeout without clearTimeout, circular references in closures. Use process.on('exit') to log active handles':

```javascript
// Monitor for common async leak patterns
const activeTimers = new Set();
const activeEventListeners = new Map();

// Wrap setTimeout to track active timers
const originalSetTimeout = global.setTimeout;
global.setTimeout = function(callback, delay, ...args) {
  const timer = originalSetTimeout(callback, delay, ...args);
  activeTimers.add(timer);
  
  const originalCallback = callback;
  const wrappedCallback = (...callbackArgs) => {
    activeTimers.delete(timer);
    return originalCallback.apply(this, callbackArgs);
  };
  
  return timer;
};

// Monitor event listener leaks
const originalAddEventListener = EventTarget.prototype.addEventListener;
EventTarget.prototype.addEventListener = function(type, listener, options) {
  if (!activeEventListeners.has(this)) {
    activeEventListeners.set(this, new Set());
  }
  activeEventListeners.get(this).add({ type, listener, options });
  
  return originalAddEventListener.call(this, type, listener, options);
};

// Monitor active handles on exit
process.on('exit', () => {
  console.log('Active timers on exit:', activeTimers.size);
  console.log('Active event listeners:', activeEventListeners.size);
  
  if (activeTimers.size > 0) {
    console.warn('Potential timer leaks detected');
  }
});

// Detect circular reference patterns
function detectCircularReferences(obj, seen = new WeakSet()) {
  if (obj && typeof obj === 'object') {
    if (seen.has(obj)) {
      return true; // Circular reference found
    }
    seen.add(obj);
    
    for (const key in obj) {
      if (detectCircularReferences(obj[key], seen)) {
        console.warn('Circular reference detected in object property:', key);
        return true;
      }
    }
  }
  return false;
}
```

## 5. Transaction Isolation and Deadlock Prevention

### Step 5.1: Implement Proper Transaction Isolation


Most PostgreSQL applications operate correctly and efficiently at READ COMMITTED. It prevents dirty reads while allowing maximum concurrency, making it the right default for OLTP workloads, API backends, and most transactional use cases.
 For this high-concurrency scenario, use READ COMMITTED with explicit row-level locking (SELECT FOR UPDATE) to balance performance and consistency:

```javascript
// Transaction boundary management with proper isolation levels
async function transferFunds(fromAccount, toAccount, amount) {
  const client = await pool.connect();
  
  try {
    // For high concurrency, use READ COMMITTED with explicit locking to balance
    // consistency with performance, avoiding SERIALIZABLE retry overhead
    await client.query('SET TRANSACTION ISOLATION LEVEL READ COMMITTED');
    await client.query('BEGIN');
    
    // Check balance with FOR UPDATE to prevent race conditions
    const balanceResult = await client.query(
      'SELECT balance FROM accounts WHERE id = $1 FOR UPDATE',
      [fromAccount]
    );
    
    if (balanceResult.rows[0].balance < amount) {
      throw new Error('Insufficient funds');
    }
    
    // Perform transfer with proper atomic operations
    await client.query(
      'UPDATE accounts SET balance = balance - $1 WHERE id = $2',
      [amount, fromAccount]
    );
    
    await client.query(
      'UPDATE accounts SET balance = balance + $1 WHERE id = $2',
      [amount, toAccount]
    );
    
    await client.query('COMMIT');
    
  } catch (error) {
    await client.query('ROLLBACK');
    
    // Handle deadlock detection with retry logic
    if (error.code === '40P01') { // Deadlock detected
      const delay = Math.random() * 1000; // Random backoff
      await new Promise(resolve => setTimeout(resolve, delay));
      console.warn('Deadlock detected, retrying transaction after delay');
      return retryTransaction();
    }
    
    throw error;
  } finally {
    client.release();
  }
}

// Explicit transaction boundary management with BEGIN/COMMIT/ROLLBACK patterns
async function executeTransactionWithProperBoundaries(operations) {
  const client = await pool.connect();
  
  try {
    await client.query('BEGIN');
    
    for (const operation of operations) {
      await client.query(operation.sql, operation.params);
    }
    
    await client.query('COMMIT');
    console.log('Transaction committed successfully');
    
  } catch (error) {
    await client.query('ROLLBACK');
    console.error('Transaction rolled back:', error.message);
    throw error;
  } finally {
    client.release();
  }
}

// Add deadlock retry logic with exponential backoff
async function executeWithDeadlockRetry(transactionFn, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await transactionFn();
    } catch (err) {
      // Handle deadlock detection with retry logic: if (err.code === '40P01') { await sleep(Math.random() * 1000); retry(); }
      if (err.code === '40P01' && attempt < maxRetries - 1) { // Deadlock detected
        const backoffDelay = Math.pow(2, attempt) * 100; // Exponential backoff
        console.warn(`Deadlock detected, retry ${attempt + 1}/${maxRetries} in ${backoffDelay}ms`);
        await new Promise(resolve => setTimeout(resolve, backoffDelay));
        continue;
      }
      throw err;
    }
  }
}
```

### Step 5.2: Isolation Level Comparison and Recommendations


Higher isolation prevents more anomalies but introduces more potential for transaction conflicts, serialization errors, and retry overhead. Choosing the right isolation level for your PostgreSQL workload is a key part of PostgreSQL performance tuning.
 READ COMMITTED allows higher concurrency but may see phantom reads. 
The Repeatable Read isolation level only sees data committed before the transaction began; it never sees either uncommitted data or changes committed by concurrent transactions during the transaction's execution. This level is different from Read Committed in that a query in a repeatable read transaction sees a snapshot as of the start of the first non-transaction-control statement in the transaction, not as of the start of the current statement within the transaction.
 SERIALIZABLE provides strongest consistency but requires retry logic for serialization failures:

```javascript
// Comprehensive isolation level configuration framework
const ISOLATION_LEVELS = {
  // High concurrency, can tolerate some inconsistency
  HIGH_CONCURRENCY: {
    level: 'READ COMMITTED',
    concurrency: 'high',
    consistency: 'eventual',
    lockContention: 'low',
    retryRequired: false,
    useCase: 'Real-time APIs, high-volume transactions',
    tradeoffs: 'READ COMMITTED allows higher concurrency but may see phantom reads vs SERIALIZABLE which prevents all anomalies but requires retry logic for serialization failures'
  },
  
  // Reporting queries that need consistent snapshot  
  REPORTING: {
    level: 'REPEATABLE READ',
    concurrency: 'medium',
    consistency: 'strong',
    lockContention: 'medium', 
    retryRequired: true,
    useCase: 'Analytics, batch processing, reports',
    tradeoffs: 'REPEATABLE READ prevents phantom reads but increases lock contention vs READ COMMITTED'
  },
  
  // Critical operations requiring full isolation
  CRITICAL: {
    level: 'SERIALIZABLE',
    concurrency: 'low',
    consistency: 'strongest',
    lockContention: 'high',
    retryRequired: true,
    useCase: 'Financial transactions, audit logs', 
    tradeoffs: 'SERIALIZABLE provides strongest consistency but requires retry logic for serialization failures vs lower isolation levels'
  }
};

async function executeWithOptimalIsolation(operation, requirements = {}) {
  const { 
    concurrencyPriority = 'medium',
    consistencyRequirement = 'strong',
    maxRetries = 3 
  } = requirements;
  
  // Select isolation level based on requirements
  let selectedLevel;
  if (concurrencyPriority === 'high') {
    selectedLevel = ISOLATION_LEVELS.HIGH_CONCURRENCY;
  } else if (consistencyRequirement === 'strongest') {
    selectedLevel = ISOLATION_LEVELS.CRITICAL;
  } else {
    selectedLevel = ISOLATION_LEVELS.REPORTING;
  }
  
  console.log(`Using ${selectedLevel.level} for ${selectedLevel.useCase} - ${selectedLevel.tradeoffs}`);
  
  const client = await pool.connect();
  let retries = 0;
  
  while (retries <= maxRetries) {
    try {
      await client.query(`SET TRANSACTION ISOLATION LEVEL ${selectedLevel.level}`);
      await client.query('BEGIN');
      
      const result = await operation(client);
      
      await client.query('COMMIT');
      return result;
      
    } catch (error) {
      await client.query('ROLLBACK');
      
      // Handle serialization failures for REPEATABLE READ and SERIALIZABLE
      if ((error.code === '40001' || error.code === '40P01') && selectedLevel.retryRequired) {
        retries++;
        if (retries <= maxRetries) {
          const backoffDelay = Math.min(1000 * Math.pow(2, retries), 5000);
          console.warn(`Serialization failure, retry ${retries}/${maxRetries} in ${backoffDelay}ms`);
          await new Promise(resolve => setTimeout(resolve, backoffDelay));
          continue;
        }
      }
      
      throw error;
    } finally {
      if (retries > maxRetries) {
        client.release();
      }
    }
  }
  
  client.release();
  throw new Error('Max retries exceeded for transaction');
}

// Usage examples with specific recommendations
app.post('/book-ticket', async (req, res) => {
  try {
    await executeWithOptimalIsolation(async (client) => {
      // For this high-concurrency scenario, use READ COMMITTED with explicit SELECT FOR UPDATE 
      // to balance consistency with performance, avoiding SERIALIZABLE retry overhead
      await client.query('SET TRANSACTION ISOLATION LEVEL READ COMMITTED');
      
      const ticket = await client.query(
        'SELECT * FROM tickets WHERE event_id = $1 AND available = true LIMIT 1 FOR UPDATE',
        [req.body.eventId]
      );
      
      if (!ticket.rows.length) {
        throw new Error('No tickets available');
      }
      
      await client.query(
        'UPDATE tickets SET available = false, user_id = $1 WHERE id = $2',
        [req.user.id, ticket.rows[0].id]
      );
      
    }, { concurrencyPriority: 'high', consistencyRequirement: 'strong' });
    
    res.json({ success: true });
  } catch (error) {
    res.status(409).json({ error: error.message });
  }
});

// Example showing PostgreSQL transaction isolation levels with atomic operations
async function atomicAccountTransfer(fromAccount, toAccount, amount) {
  const client = await pool.connect();
  
  try {
    // Use REPEATABLE READ for consistency requirements across multiple queries
    await client.query('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');
    await client.query('BEGIN');
    
    // Atomic operation pattern: read with lock, modify, write
    const fromBalance = await client.query(
      'SELECT balance FROM accounts WHERE id = $1 FOR UPDATE',
      [fromAccount]
    );
    
    if (fromBalance.rows[0].balance < amount) {
      throw new Error('Insufficient funds');
    }
    
    // Atomic updates - both succeed or both fail
    await client.query(
      'UPDATE accounts SET balance = balance - $1 WHERE id = $2',
      [amount, fromAccount]
    );
    
    await client.query(
      'UPDATE accounts SET balance = balance + $1 WHERE id = $2', 
      [amount, toAccount]
    );
    
    await client.query('COMMIT');
    
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
```

## 6. Node.js Event Loop Optimization

### Step 6.1: Optimize Async Patterns

Add async optimization patterns: 'Avoid await in loops: use Promise.all([...array.map(async item => await process(item))]). Use Promise.allSettled for partial failure tolerance':

```javascript
// ❌ Inefficient - Sequential processing blocks event loop
async function processUsersSequentially(userIds) {
  const results = [];
  for (const id of userIds) {
    const user = await client.query('SELECT * FROM users WHERE id = $1', [id]);
    results.push(user.rows[0]);
  }
  return results;
}

// ✅ Efficient - Parallel processing with proper connection management
async function processUsersInParallel(userIds) {
  const promises = userIds.map(async (id) => {
    const client = await pool.connect();
    try {
      const result = await client.query('SELECT * FROM users WHERE id = $1', [id]);
      return result.rows[0];
    } finally {
      client.release();
    }
  });
  
  // Use Promise.all for parallel execution, Promise.allSettled for partial failure tolerance
  const results = await Promise.allSettled(promises);
  return results
    .filter(result => result.status === 'fulfilled')
    .map(result => result.value);
}

// Optimize concurrent query patterns - Use Promise.all optimization
async function getMultipleUsers(userIds) {
  // const [user, posts] = await Promise.all([getUserById(id), getPostsByUserId(id)]);
  const [userDetails, userPosts, userSettings] = await Promise.all([
    processUsersInParallel(userIds.slice(0, 10)),
    getPostsByUserIds(userIds),
    getSettingsByUserIds(userIds)
  ]);
  
  return { userDetails, userPosts, userSettings };
}

// Batched processing to prevent overwhelming the connection pool
async function processBatchedUsers(userIds,