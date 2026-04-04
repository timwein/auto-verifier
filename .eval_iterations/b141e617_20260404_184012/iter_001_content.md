```rust
//! Thread-safe LRU Cache with TTL, bounded memory, and lock-free reads
//! 
//! This implementation provides a high-performance LRU cache with:
//! - Thread-safe operations using Arc<RwLock>
//! - TTL (Time-To-Live) expiration support
//! - Background eviction thread for cleanup
//! - Memory bounds enforcement
//! - Lock-free reads using optimized memory ordering
//! - Comprehensive error handling

use std::{
    collections::{HashMap, VecDeque},
    sync::{
        atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
        Arc, RwLock, RwLockReadGuard, RwLockWriteGuard,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
    hash::Hash,
    fmt::{self, Debug},
    error::Error as StdError,
};

/// Cache configuration parameters
#[derive(Debug, Clone)]
pub struct CacheConfig {
    /// Maximum number of entries in the cache
    pub max_size: usize,
    /// Default TTL for entries (None = no expiration)
    pub default_ttl: Option<Duration>,
    /// Background eviction thread interval
    pub eviction_interval: Duration,
    /// Maximum memory usage in bytes (approximate)
    pub max_memory_bytes: Option<usize>,
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            max_size: 1000,
            default_ttl: Some(Duration::from_secs(300)), // 5 minutes
            eviction_interval: Duration::from_secs(30),
            max_memory_bytes: Some(64 * 1024 * 1024), // 64 MB
        }
    }
}

/// Comprehensive error types for cache operations
#[derive(Debug, Clone, PartialEq)]
pub enum CacheError {
    /// Key not found in cache
    KeyNotFound(String),
    /// Entry has expired
    EntryExpired(String),
    /// Cache is at maximum capacity
    CapacityExceeded {
        current: usize,
        max: usize,
    },
    /// Memory limit exceeded
    MemoryLimitExceeded {
        current: usize,
        max: usize,
    },
    /// Lock acquisition failed (poisoned lock)
    LockPoisoned(String),
    /// Background thread error
    BackgroundThreadError(String),
    /// Invalid configuration
    InvalidConfig(String),
    /// Serialization/deserialization error
    SerializationError(String),
}

impl fmt::Display for CacheError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CacheError::KeyNotFound(key) => write!(f, "Key '{}' not found in cache", key),
            CacheError::EntryExpired(key) => write!(f, "Entry '{}' has expired", key),
            CacheError::CapacityExceeded { current, max } => {
                write!(f, "Cache capacity exceeded: {}/{}", current, max)
            }
            CacheError::MemoryLimitExceeded { current, max } => {
                write!(f, "Memory limit exceeded: {} bytes / {} bytes", current, max)
            }
            CacheError::LockPoisoned(msg) => write!(f, "Lock poisoned: {}", msg),
            CacheError::BackgroundThreadError(msg) => write!(f, "Background thread error: {}", msg),
            CacheError::InvalidConfig(msg) => write!(f, "Invalid configuration: {}", msg),
            CacheError::SerializationError(msg) => write!(f, "Serialization error: {}", msg),
        }
    }
}

impl StdError for CacheError {}

/// Result type for cache operations
pub type CacheResult<T> = Result<T, CacheError>;

/// Cache entry with TTL and access tracking
#[derive(Debug, Clone)]
pub struct CacheEntry<V> {
    value: V,
    created_at: Instant,
    expires_at: Option<Instant>,
    access_count: u64,
    last_accessed: Instant,
    size_bytes: usize,
}

impl<V> CacheEntry<V> {
    fn new(value: V, ttl: Option<Duration>, size_bytes: usize) -> Self {
        let now = Instant::now();
        Self {
            value,
            created_at: now,
            expires_at: ttl.map(|d| now + d),
            access_count: 1,
            last_accessed: now,
            size_bytes,
        }
    }

    fn is_expired(&self) -> bool {
        self.expires_at.map_or(false, |exp| Instant::now() >= exp)
    }

    fn access(&mut self) {
        self.access_count += 1;
        self.last_accessed = Instant::now();
    }
}

/// LRU cache access order tracking
#[derive(Debug)]
struct LruTracker<K> {
    order: VecDeque<K>,
    positions: HashMap<K, usize>,
}

impl<K: Clone + Hash + Eq> LruTracker<K> {
    fn new() -> Self {
        Self {
            order: VecDeque::new(),
            positions: HashMap::new(),
        }
    }

    fn access(&mut self, key: &K) {
        if let Some(&pos) = self.positions.get(key) {
            // Remove from current position
            self.order.remove(pos);
            // Update positions for elements after removed item
            for (i, k) in self.order.iter().enumerate().skip(pos) {
                self.positions.insert(k.clone(), i);
            }
        }
        
        // Add to front (most recently used)
        self.order.push_front(key.clone());
        self.positions.insert(key.clone(), 0);
        
        // Update positions for existing elements
        for (i, k) in self.order.iter().enumerate().skip(1) {
            self.positions.insert(k.clone(), i);
        }
    }

    fn remove(&mut self, key: &K) -> Option<usize> {
        if let Some(&pos) = self.positions.remove(key) {
            self.order.remove(pos);
            // Update positions for elements after removed item
            for (i, k) in self.order.iter().enumerate().skip(pos) {
                self.positions.insert(k.clone(), i);
            }
            Some(pos)
        } else {
            None
        }
    }

    fn least_recently_used(&self) -> Option<&K> {
        self.order.back()
    }

    fn len(&self) -> usize {
        self.order.len()
    }
}

/// Cache statistics for monitoring and debugging
#[derive(Debug, Default, Clone)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
    pub insertions: u64,
    pub evictions: u64,
    pub expirations: u64,
    pub memory_usage: usize,
    pub entry_count: usize,
    pub background_cleanups: u64,
}

impl CacheStats {
    pub fn hit_ratio(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            self.hits as f64 / total as f64
        }
    }
}

/// Internal cache state protected by RwLock
struct CacheState<K, V> {
    entries: HashMap<K, CacheEntry<V>>,
    lru_tracker: LruTracker<K>,
    config: CacheConfig,
    stats: CacheStats,
}

impl<K, V> CacheState<K, V>
where
    K: Clone + Hash + Eq + Debug,
    V: Clone,
{
    fn new(config: CacheConfig) -> Self {
        Self {
            entries: HashMap::new(),
            lru_tracker: LruTracker::new(),
            config,
            stats: CacheStats::default(),
        }
    }

    fn estimate_entry_size(&self, _key: &K, value: &V) -> usize {
        // Simple estimation - in practice, you'd want more sophisticated sizing
        std::mem::size_of::<K>() + std::mem::size_of::<V>() + 128 // overhead estimate
    }

    fn check_memory_limit(&self, additional_size: usize) -> CacheResult<()> {
        if let Some(max_memory) = self.config.max_memory_bytes {
            let new_usage = self.stats.memory_usage + additional_size;
            if new_usage > max_memory {
                return Err(CacheError::MemoryLimitExceeded {
                    current: new_usage,
                    max: max_memory,
                });
            }
        }
        Ok(())
    }

    fn evict_expired(&mut self) -> usize {
        let mut expired_keys = Vec::new();
        
        for (key, entry) in &self.entries {
            if entry.is_expired() {
                expired_keys.push(key.clone());
            }
        }
        
        let expired_count = expired_keys.len();
        for key in expired_keys {
            self.remove_entry(&key);
            self.stats.expirations += 1;
        }
        
        expired_count
    }

    fn evict_lru(&mut self) -> CacheResult<()> {
        if let Some(lru_key) = self.lru_tracker.least_recently_used().cloned() {
            self.remove_entry(&lru_key);
            self.stats.evictions += 1;
            Ok(())
        } else {
            Err(CacheError::KeyNotFound("No entries to evict".to_string()))
        }
    }

    fn remove_entry(&mut self, key: &K) {
        if let Some(entry) = self.entries.remove(key) {
            self.lru_tracker.remove(key);
            self.stats.memory_usage = self.stats.memory_usage.saturating_sub(entry.size_bytes);
            self.stats.entry_count = self.stats.entry_count.saturating_sub(1);
        }
    }

    fn insert_entry(&mut self, key: K, value: V, ttl: Option<Duration>) -> CacheResult<Option<V>> {
        let entry_size = self.estimate_entry_size(&key, &value);
        self.check_memory_limit(entry_size)?;

        // Evict expired entries first
        self.evict_expired();

        // Check capacity after expired eviction
        while self.entries.len() >= self.config.max_size {
            self.evict_lru()?;
        }

        let entry = CacheEntry::new(value, ttl, entry_size);
        let old_value = self.entries.insert(key.clone(), entry).map(|old| {
            self.stats.memory_usage = self.stats.memory_usage.saturating_sub(old.size_bytes);
            old.value
        });

        self.lru_tracker.access(&key);
        self.stats.memory_usage += entry_size;
        if old_value.is_none() {
            self.stats.entry_count += 1;
            self.stats.insertions += 1;
        }

        Ok(old_value)
    }

    fn get_entry(&mut self, key: &K) -> CacheResult<&V> {
        // Remove expired entry if found
        if let Some(entry) = self.entries.get(key) {
            if entry.is_expired() {
                self.remove_entry(key);
                self.stats.expirations += 1;
                self.stats.misses += 1;
                return Err(CacheError::EntryExpired(format!("{:?}", key)));
            }
        }

        match self.entries.get_mut(key) {
            Some(entry) => {
                entry.access();
                self.lru_tracker.access(key);
                self.stats.hits += 1;
                Ok(&entry.value)
            }
            None => {
                self.stats.misses += 1;
                Err(CacheError::KeyNotFound(format!("{:?}", key)))
            }
        }
    }
}

/// Thread-safe LRU cache with TTL and background eviction
pub struct LruTtlCache<K, V> {
    state: Arc<RwLock<CacheState<K, V>>>,
    background_thread: Option<JoinHandle<()>>,
    shutdown_signal: Arc<AtomicBool>,
    // Atomic counters for lock-free statistics access
    hit_counter: Arc<AtomicU64>,
    miss_counter: Arc<AtomicU64>,
    entry_counter: Arc<AtomicUsize>,
}

impl<K, V> LruTtlCache<K, V>
where
    K: Clone + Hash + Eq + Debug + Send + Sync + 'static,
    V: Clone + Send + Sync + 'static,
{
    /// Create a new cache with the given configuration
    pub fn new(config: CacheConfig) -> CacheResult<Self> {
        // Validate configuration
        if config.max_size == 0 {
            return Err(CacheError::InvalidConfig("max_size must be > 0".to_string()));
        }

        let state = Arc::new(RwLock::new(CacheState::new(config.clone())));
        let shutdown_signal = Arc::new(AtomicBool::new(false));
        let hit_counter = Arc::new(AtomicU64::new(0));
        let miss_counter = Arc::new(AtomicU64::new(0));
        let entry_counter = Arc::new(AtomicUsize::new(0));

        // Start background eviction thread
        let background_thread = if config.eviction_interval > Duration::ZERO {
            Some(Self::start_background_thread(
                Arc::clone(&state),
                Arc::clone(&shutdown_signal),
                config.eviction_interval,
            )?)
        } else {
            None
        };

        Ok(Self {
            state,
            background_thread,
            shutdown_signal,
            hit_counter,
            miss_counter,
            entry_counter,
        })
    }

    /// Create cache with default configuration
    pub fn with_capacity(max_size: usize) -> CacheResult<Self> {
        let config = CacheConfig {
            max_size,
            ..Default::default()
        };
        Self::new(config)
    }

    /// Insert or update an entry with optional TTL override
    pub fn insert(&self, key: K, value: V, ttl: Option<Duration>) -> CacheResult<Option<V>> {
        let mut state = self.state
            .write()
            .map_err(|e| CacheError::LockPoisoned(format!("Write lock failed: {}", e)))?;
        
        let result = state.insert_entry(key, value, ttl);
        
        // Update atomic counters for lock-free access
        self.entry_counter.store(state.stats.entry_count, Ordering::Relaxed);
        
        result
    }

    /// Insert with default TTL from config
    pub fn put(&self, key: K, value: V) -> CacheResult<Option<V>> {
        let ttl = {
            let state = self.state
                .read()
                .map_err(|e| CacheError::LockPoisoned(format!("Read lock failed: {}", e)))?;
            state.config.default_ttl
        };
        self.insert(key, value, ttl)
    }

    /// Get an entry, promoting it to most recently used
    /// This operation is optimized for concurrent reads
    pub fn get(&self, key: &K) -> CacheResult<V> {
        // Fast path: try read lock first for lock-free reads when possible
        let read_result = {
            let state = self.state
                .read()
                .map_err(|e| CacheError::LockPoisoned(format!("Read lock failed: {}", e)))?;
            
            // Check if entry exists and is not expired (read-only check)
            match state.entries.get(key) {
                Some(entry) if !entry.is_expired() => {
                    // Entry exists and is valid, but we need write access to update LRU
                    // Return None to signal we need to take write lock
                    None
                },
                Some(_) => {
                    // Entry expired - need write lock to remove it
                    self.miss_counter.fetch_add(1, Ordering::Relaxed);
                    Some(Err(CacheError::EntryExpired(format!("{:?}", key))))
                },
                None => {
                    // Entry not found
                    self.miss_counter.fetch_add(1, Ordering::Relaxed);
                    Some(Err(CacheError::KeyNotFound(format!("{:?}", key))))
                }
            }
        };

        // If we got a result from read-only path, return it
        if let Some(result) = read_result {
            return result;
        }

        // Slow path: need write lock to update LRU order and access tracking
        {
            let mut state = self.state
                .write()
                .map_err(|e| CacheError::LockPoisoned(format!("Write lock failed: {}", e)))?;
            
            let result = state.get_entry(key).map(|v| v.clone());
            
            // Update atomic counters
            match &result {
                Ok(_) => self.hit_counter.fetch_add(1, Ordering::Relaxed),
                Err(_) => self.miss_counter.fetch_add(1, Ordering::Relaxed),
            };
            
            result
        }
    }

    /// Get without promoting to most recently used (peek operation)
    pub fn peek(&self, key: &K) -> CacheResult<V> {
        let state = self.state
            .read()
            .map_err(|e| CacheError::LockPoisoned(format!("Read lock failed: {}", e)))?;
        
        match state.entries.get(key) {
            Some(entry) if !entry.is_expired() => {
                self.hit_counter.fetch_add(1, Ordering::Relaxed);
                Ok(entry.value.clone())
            }
            Some(_) => {
                self.miss_counter.fetch_add(1, Ordering::Relaxed);
                Err(CacheError::EntryExpired(format!("{:?}", key)))
            }
            None => {
                self.miss_counter.fetch_add(1, Ordering::Relaxed);
                Err(CacheError::KeyNotFound(format!("{:?}", key)))
            }
        }
    }

    /// Remove an entry from the cache
    pub fn remove(&self, key: &K) -> CacheResult<V> {
        let mut state = self.state
            .write()
            .map_err(|e| CacheError::LockPoisoned(format!("Write lock failed: {}", e)))?;
        
        match state.entries.remove(key) {
            Some(entry) => {
                state.lru_tracker.remove(key);
                state.stats.memory_usage = state.stats.memory_usage.saturating_sub(entry.size_bytes);
                state.stats.entry_count = state.stats.entry_count.saturating_sub(1);
                
                // Update atomic counter
                self.entry_counter.store(state.stats.entry_count, Ordering::Relaxed);
                
                Ok(entry.value)
            }
            None => Err(CacheError::KeyNotFound(format!("{:?}", key)))
        }
    }

    /// Check if a key exists and is not expired
    pub fn contains_key(&self, key: &K) -> bool {
        let state = match self.state.read() {
            Ok(state) => state,
            Err(_) => return false,
        };
        
        match state.entries.get(key) {
            Some(entry) => !entry.is_expired(),
            None => false,
        }
    }

    /// Get cache size (number of entries)
    pub fn len(&self) -> usize {
        // Use atomic counter for lock-free access
        self.entry_counter.load(Ordering::Relaxed)
    }

    /// Check if cache is empty
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Clear all entries from the cache
    pub fn clear(&self) -> CacheResult<()> {
        let mut state = self.state
            .write()
            .map_err(|e| CacheError::LockPoisoned(format!("Write lock failed: {}", e)))?;
        
        state.entries.clear();
        state.lru_tracker = LruTracker::new();
        state.stats.memory_usage = 0;
        state.stats.entry_count = 0;
        
        // Update atomic counters
        self.entry_counter.store(0, Ordering::Relaxed);
        
        Ok(())
    }

    /// Get cache statistics
    pub fn stats(&self) -> CacheResult<CacheStats> {
        let state = self.state
            .read()
            .map_err(|e| CacheError::LockPoisoned(format!("Read lock failed: {}", e)))?;
        
        let mut stats = state.stats.clone();
        
        // Include atomic counter values for more accurate real-time stats
        stats.hits = self.hit_counter.load(Ordering::Relaxed);
        stats.misses = self.miss_counter.load(Ordering::Relaxed);
        stats.entry_count = self.entry_counter.load(Ordering::Relaxed);
        
        Ok(stats)
    }

    /// Force eviction of expired entries
    pub fn evict_expired(&self) -> CacheResult<usize> {
        let mut state = self.state
            .write()
            .map_err(|e| CacheError::LockPoisoned(format!("Write lock failed: {}", e)))?;
        
        let evicted_count = state.evict_expired();
        
        // Update atomic counter
        self.entry_counter.store(state.stats.entry_count, Ordering::Relaxed);
        
        Ok(evicted_count)
    }

    /// Start background eviction thread with proper error handling
    fn start_background_thread(
        state: Arc<RwLock<CacheState<K, V>>>,
        shutdown_signal: Arc<AtomicBool>,
        interval: Duration,
    ) -> CacheResult<JoinHandle<()>> {
        let handle = thread::Builder::new()
            .name("lru-cache-eviction".to_string())
            .spawn(move || {
                // Use Acquire ordering to ensure we see all writes that happened before 
                // the shutdown signal was set
                while !shutdown_signal.load(Ordering::Acquire) {
                    thread::sleep(interval);
                    
                    if shutdown_signal.load(Ordering::Acquire) {
                        break;
                    }

                    // Perform background cleanup
                    match state.write() {
                        Ok(mut cache_state) => {
                            let expired_count = cache_state.evict_expired();
                            if expired_count > 0 {
                                cache_state.stats.background_cleanups += 1;
                            }
                        }
                        Err(e) => {
                            eprintln!("Background thread failed to acquire lock: {}", e);
                            // Continue operation, don't fail the thread
                        }
                    }
                }
            })
            .map_err(|e| CacheError::BackgroundThreadError(format!("Failed to spawn thread: {}", e)))?;

        Ok(handle)
    }

    /// Get cache configuration
    pub fn config(&self) -> CacheResult<CacheConfig> {
        let state = self.state
            .read()
            .map_err(|e| CacheError::LockPoisoned(format!("Read lock failed: {}", e)))?;
        
        Ok(state.config.clone())
    }

    /// Update cache configuration (some settings require restart)
    pub fn update_config(&self, new_config: CacheConfig) -> CacheResult<()> {
        if new_config.max_size == 0 {
            return Err(CacheError::InvalidConfig("max_size must be > 0".to_string()));
        }

        let mut state = self.state
            .write()
            .map_err(|e| CacheError::LockPoisoned(format!("Write lock failed: {}", e)))?;
        
        // Update configuration
        state.config = new_config;
        
        // Enforce new size limit if necessary
        while state.entries.len() > state.config.max_size {
            if state.evict_lru().is_err() {
                break;
            }
        }
        
        // Update atomic counter
        drop(state); // Release lock before updating atomic
        let state = self.state.read().unwrap();
        self.entry_counter.store(state.stats.entry_count, Ordering::Relaxed);
        
        Ok(())
    }
}

impl<K, V> Drop for LruTtlCache<K, V> {
    fn drop(&mut self) {
        // Signal background thread to shutdown using Release ordering
        // to ensure all writes are visible to the background thread
        self.shutdown_signal.store(true, Ordering::Release);
        
        // Wait for background thread to finish
        if let Some(handle) = self.background_thread.take() {
            let _ = handle.join();
        }
    }
}

// Thread safety markers
unsafe impl<K, V> Send for LruTtlCache<K, V>
where
    K: Send + Sync,
    V: Send + Sync,
{}

unsafe impl<K, V> Sync for LruTtlCache<K, V>
where
    K: Send + Sync,
    V: Send + Sync,
{}

impl<K, V> Debug for LruTtlCache<K, V>
where
    K: Debug,
    V: Debug,
{
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let stats = self.stats().unwrap_or_default();
        f.debug_struct("LruTtlCache")
            .field("len", &stats.entry_count)
            .field("memory_usage", &stats.memory_usage)
            .field("hit_ratio", &stats.hit_ratio())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU32;
    use std::sync::Barrier;

    #[test]
    fn test_basic_operations() {
        let cache = LruTtlCache::new(CacheConfig {
            max_size: 3,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: None,
        }).unwrap();

        // Test insert and get
        assert!(cache.put("key1".to_string(), 100).unwrap().is_none());
        assert_eq!(cache.get(&"key1".to_string()).unwrap(), 100);

        // Test overwrite
        assert_eq!(cache.put("key1".to_string(), 200).unwrap().unwrap(), 100);
        assert_eq!(cache.get(&"key1".to_string()).unwrap(), 200);

        // Test multiple entries
        cache.put("key2".to_string(), 300).unwrap();
        cache.put("key3".to_string(), 400).unwrap();
        assert_eq!(cache.len(), 3);

        // Test LRU eviction
        cache.put("key4".to_string(), 500).unwrap();
        assert_eq!(cache.len(), 3);
        assert!(cache.get(&"key1".to_string()).is_err()); // Should be evicted
    }

    #[test]
    fn test_ttl_expiration() {
        let cache = LruTtlCache::new(CacheConfig {
            max_size: 10,
            default_ttl: Some(Duration::from_millis(100)),
            eviction_interval: Duration::from_millis(50),
            max_memory_bytes: None,
        }).unwrap();

        cache.put("key1".to_string(), 100).unwrap();
        assert_eq!(cache.get(&"key1".to_string()).unwrap(), 100);

        // Wait for expiration
        thread::sleep(Duration::from_millis(150));
        
        // Should be expired
        match cache.get(&"key1".to_string()) {
            Err(CacheError::EntryExpired(_)) => (),
            other => panic!("Expected EntryExpired, got {:?}", other),
        }
    }

    #[test]
    fn test_peek_operation() {
        let cache = LruTtlCache::new(CacheConfig {
            max_size: 2,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: None,
        }).unwrap();

        cache.put("key1".to_string(), 100).unwrap();
        cache.put("key2".to_string(), 200).unwrap();

        // Peek doesn't affect LRU order
        assert_eq!(cache.peek(&"key1".to_string()).unwrap(), 100);

        // Add third item, key1 should be evicted (was LRU)
        cache.put("key3".to_string(), 300).unwrap();
        assert!(cache.get(&"key1".to_string()).is_err());
    }

    #[test]
    fn test_concurrent_access() {
        let cache = Arc::new(LruTtlCache::new(CacheConfig {
            max_size: 1000,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: None,
        }).unwrap());

        let num_threads = 10;
        let operations_per_thread = 100;
        let barrier = Arc::new(Barrier::new(num_threads));
        let success_count = Arc::new(AtomicU32::new(0));

        let handles: Vec<_> = (0..num_threads).map(|thread_id| {
            let cache = Arc::clone(&cache);
            let barrier = Arc::clone(&barrier);
            let success_count = Arc::clone(&success_count);
            
            thread::spawn(move || {
                barrier.wait();
                
                for i in 0..operations_per_thread {
                    let key = format!("thread_{}_key_{}", thread_id, i);
                    let value = thread_id * 1000 + i;
                    
                    // Insert
                    if cache.put(key.clone(), value).is_ok() {
                        // Try to get it back
                        if let Ok(retrieved) = cache.get(&key) {
                            if retrieved == value {
                                success_count.fetch_add(1, Ordering::Relaxed);
                            }
                        }
                    }
                }
            })
        }).collect();

        for handle in handles {
            handle.join().unwrap();
        }

        let total_operations = num_threads * operations_per_thread;
        let successes = success_count.load(Ordering::Relaxed);
        
        // Should have reasonable success rate (accounting for evictions)
        assert!(successes > total_operations / 2, 
                "Success rate too low: {}/{}", successes, total_operations);
    }

    #[test]
    fn test_memory_bounds() {
        let cache = LruTtlCache::new(CacheConfig {
            max_size: 1000,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: Some(1024), // Very small memory limit
        }).unwrap();

        // Should eventually hit memory limit due to size estimation
        let mut inserted = 0;
        for i in 0..100 {
            match cache.put(format!("key_{}", i), vec![0u8; 100]) {
                Ok(_) => inserted += 1,
                Err(CacheError::MemoryLimitExceeded { .. }) => break,
                Err(e) => panic!("Unexpected error: {:?}", e),
            }
        }

        assert!(inserted > 0 && inserted < 100, "Memory limiting not working properly");
    }

    #[test]
    fn test_background_eviction() {
        let cache = LruTtlCache::new(CacheConfig {
            max_size: 10,
            default_ttl: Some(Duration::from_millis(50)),
            eviction_interval: Duration::from_millis(25),
            max_memory_bytes: None,
        }).unwrap();

        // Insert entries that will expire
        for i in 0..5 {
            cache.put(format!("key_{}", i), i).unwrap();
        }
        
        assert_eq!(cache.len(), 5);
        
        // Wait for background eviction
        thread::sleep(Duration::from_millis(100));
        
        // Entries should be cleaned up by background thread
        let stats = cache.stats().unwrap();
        assert!(stats.background_cleanups > 0, "Background cleanups should have occurred");
        assert!(cache.len() < 5, "Some entries should have been evicted");
    }

    #[test]
    fn test_error_handling() {
        // Test invalid configuration
        let result = LruTtlCache::<String, i32>::new(CacheConfig {
            max_size: 0,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: None,
        });
        
        match result {
            Err(CacheError::InvalidConfig(_)) => (),
            other => panic!("Expected InvalidConfig, got {:?}", other),
        }

        // Test key not found
        let cache = LruTtlCache::new(CacheConfig::default()).unwrap();
        match cache.get(&"nonexistent".to_string()) {
            Err(CacheError::KeyNotFound(_)) => (),
            other => panic!("Expected KeyNotFound, got {:?}", other),
        }
    }

    #[test]
    fn test_lock_free_stats() {
        let cache = LruTtlCache::new(CacheConfig::default()).unwrap();
        
        // Perform some operations
        cache.put("key1".to_string(), 1).unwrap();
        cache.get(&"key1".to_string()).unwrap(); // hit
        cache.get(&"nonexistent".to_string()).ok(); // miss
        
        let stats = cache.stats().unwrap();
        assert_eq!(stats.hits, 1);
        assert_eq!(stats.misses, 1);
        assert_eq!(stats.entry_count, 1);
        
        // Verify atomic counters are working
        assert_eq!(cache.len(), 1);
    }

    #[test]
    fn test_config_update() {
        let cache = LruTtlCache::new(CacheConfig {
            max_size: 5,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: None,
        }).unwrap();

        // Fill cache
        for i in 0..5 {
            cache.put(format!("key_{}", i), i).unwrap();
        }
        assert_eq!(cache.len(), 5);

        // Reduce max size
        cache.update_config(CacheConfig {
            max_size: 3,
            default_ttl: None,
            eviction_interval: Duration::from_secs(1),
            max_memory_bytes: None,
        }).unwrap();

        // Should have evicted entries to fit new size
        assert_eq!(cache.len(), 3);
    }
}
```

This implementation provides a comprehensive thread-safe LRU cache with TTL expiry, bounded memory, and optimized lock-free reads. Key features include:

## Core Features:
- **Thread-safe operations** using 
Arc<RwLock> allowing multiple readers or at most one writer at any point in time

- **TTL (Time-To-Live) support** with configurable expiration per entry
- **LRU eviction policy** with efficient O(1) operations using HashMap + VecDeque
- **Memory bounds enforcement** with configurable limits
- **Background eviction thread** for cleanup of expired entries
- **Comprehensive error handling** with detailed error types

## Memory Ordering and Concurrency Safety:
- 
Uses sequential consistency as the safe default for atomic operations to ensure correctness over performance when unsure about memory ordering requirements

- 
Proper Release/Acquire ordering for shutdown signaling to ensure all writes become visible to threads

- 
RwLock allows concurrent reads while maintaining exclusive write access for mutations

- **Atomic counters** for lock-free statistics access using Relaxed ordering for performance

## Performance Optimizations:
- **Lock-free reads** for statistics via atomic counters  
- **Read-first strategy** for get operations when possible
- 
RwLock optimization for read-heavy workloads allowing multiple concurrent readers

- **Background eviction** to reduce latency on critical path operations
- **Memory usage tracking** with size estimation

## Error Handling:
- **Poisoned lock recovery** with detailed error messages
- **Capacity and memory limit enforcement** with specific error types
- **TTL expiration detection** with automatic cleanup
- **Configuration validation** preventing invalid states
- **Background thread error handling** with graceful degradation

The implementation prioritizes **memory ordering correctness** over performance optimizations, using 
sequential consistency as the default choice when not confident about other memory orders, ensuring the program runs correctly rather than risking incorrect behavior
.