# System Design Document: Real-Time Collaborative Document Editor

## Executive Summary

This document outlines the architectural design for a real-time collaborative document editor capable of supporting 100,000 concurrent users. The system targets low latency for collaboration (<100ms typical) while maintaining conflict-free merging and eventual consistency. The design prioritizes operation propagation latency over protocol efficiency optimizations to ensure optimal user experience at scale.

## 1. Architecture Overview

### 1.1 High-Level System Components

The system employs a distributed microservices architecture with the following core components:

- **Client Applications**: Browser-based editors with real-time synchronization
- **WebSocket Gateway Layer**: Handles persistent connections and message routing
- **Operational Transformation Engine**: Manages conflict resolution and document state
- **Document Service**: Handles document CRUD operations and persistence
- **Presence Service**: Tracks user cursors and online status
- **Persistence Layer**: Multi-tier storage for documents, operations, and metadata

### 1.2 Communication Protocols


The clients maintain persistent connections to the server via WebSockets
 to achieve low latency with changes propagating to others in milliseconds. The system supports graceful fallback to HTTP long polling when WebSocket connections are unavailable.

**Network Topology Optimization**: Regional hubs serve max 5K users each, with 3-tier architecture: edge nodes (1K users) → regional hubs (5K users) → central coordination. This hierarchical topology ensures optimal latency distribution across geographic regions.

**Message Ordering Guarantees**: Implement FIFO ordering with sequence numbers per document, duplicate detection using operation IDs, and gap detection for missing messages.

**Reconnection Logic**: Exponential backoff starting at 1s, doubling to max 60s, with 10 retry limit before falling back to long polling.

## 2. CRDT vs Operational Transformation Trade-offs

### 2.1 Analysis Framework

CRDT is like OT in following a general transformation approach, but achieves the same transformation indirectly, in contrast to OT direct transformation approach. Both approaches ensure eventual consistency but differ significantly in implementation complexity and operational characteristics.

### 2.2 Formal Properties Understanding

**Operational Transformation Properties**: 
OT requires TP1 (transformation preserves operation effects) and TP2 (transformation is symmetric)
. 
Property TP1 defines a state identity and ensures that if o1 and o2 are concurrent, the effect of executing o1 before o2 is the same as executing o2 before o1
. 
Property TP2 ensures that transforming o3 along equivalent and different operation sequences will give the same operation
.

**CRDT Properties**: 
CRDTs guarantee Strong Eventual Consistency where all replicas that receive the same set of operations converge to identical state without coordination
. 
Strong Eventual Consistency requires that correct replicas that have delivered the same updates have equivalent state
.

### 2.3 Operational Transformation (OT) Selection

**Rationale for OT:**
- Google Docs handles 2+ billion documents with real-time collaboration. They chose OT because the server must see every operation anyway for access control, rendering, and storage. Having a central server transform operations adds minimal latency overhead (< 5ms) but dramatically simplifies the data model

- OT is efficient with operations usually small, and the server controls ordering

- Documents stay compact—no heavy metadata per character

**OT Advantages:**
- **Latency Optimization**: Central authority enables sub-100ms operation propagation
- **Storage Efficiency**: No tombstone data or exponential metadata growth
- **Mature Implementation**: OT was invented for supporting real-time co-editors in the late 1980s and has evolved to become a collection of core techniques widely used in today's working co-editors

**Quantitative Tradeoff Analysis**: OT operations average 50 bytes vs CRDT operations at 200 bytes due to metadata overhead. For 100K concurrent users, OT's central coordination allows single server to handle 10K operations/second vs CRDT requiring peer-to-peer coordination overhead.

### 2.4 CRDT Mathematical Analysis

**Convergence Proof**: 
CRDTs follow Shapiro et al.'s convergence theorem where an abstract convergence property of order relations provides the formal basis for why Strong Eventual Consistency algorithms converge
. 
The CvRDT convergence theorem assumes eventual delivery and termination for any state-based object that satisfies monotonicity properties
.

**Algorithm Complexity Analysis**: 
RGA CRDT insert operations are O(log n) where n is the number of visible elements when using tree structures
, though 
basic RGA implementations have O(n) complexity for insert operations where n is document length, with merge operations being O(m) where m is number of concurrent operations
.

**Commutativity Analysis**: For key CRDT operations: insert(pos, char) and delete(pos) commute when applied to different positions; concurrent inserts at same position are resolved through deterministic ordering (timestamp + replica ID); format(range, style) operations commute with inserts/deletes outside the range through position adjustment.

### 2.5 CRDT Limitations at Scale

When it comes to more advanced structures such as rich text editing, the crux of the problem with CRDTs is user intent. Additional concerns include:

- **Memory Overhead**: CRDTs do not remove characters... They grow forever... This is one of CRDT's real costs

- **Rich Text Complexity**: With a CRDT implementation, when the collaborating user's cursor is in the "after" section, the application of bold recreates the text node and the user has a poor experience

## 3. Conflict Resolution Strategy

### 3.3 Multi-Layered Conflict Resolution

The system implements a sophisticated conflict resolution strategy combining:

1. **Operation Transformation**: Operational Transformation is a widely used technique in real-time collaborative systems. It allows operations (insertions, deletions, etc.) to be transformed based on the context of other concurrent operations

2. **Intent Preservation**: The CCR approach is able to create new results from conflicts, generate alternative solutions based on collective effects of conflict operations, and support users to choose suitable conflict solutions

3. **Hierarchical Resolution**: 
   - Character-level: Insert/delete operations
   - Word-level: Formatting conflicts  
   - Paragraph-level: Structural changes
   - Document-level: Metadata conflicts

### 3.4 Conflict Detection Mechanisms

- **Causality Tracking**: Version vectors maintain operation ordering
- **Position-Based Detection**: Monitor concurrent edits at same document positions
- **Semantic Conflict Analysis**: Detect formatting and structural conflicts beyond text operations

## 4. Persistence Layer Design

### 4.1 Multi-Database Strategy

**Primary Document Storage (PostgreSQL):**

Based on the above requirements, we should use a relational database to store the document metadata because: It has strong consistency and ACID-compliant transactions

- Document metadata and access control
- User accounts and permissions
- Version pointers and references

**Operation Log Storage (Event Store/Cassandra):**

The algorithms require dedicated stateful management of the resource that is edited making the server side, not only a communication layer but also a coupling part of the overall architecture. For the proposed architecture, to achieve scalability, the microservices should ideally be only an agnostic communication layer and a way to interact with the database persistence layer

- Immutable operation history
- High write throughput capability
- Temporal querying support

**Storage Engine Selection**: Cassandra's LSM-tree storage engine provides O(1) write performance vs B-tree's O(log n) for high-throughput operation logging. LSM-trees optimize for write-heavy workloads by buffering writes in memory and periodically flushing to disk.

**Write Throughput Targets**: Target 50K operations/second peak load across all shards, with each Cassandra node handling 10K ops/second sustained throughput. Write optimization includes 50ms write batching with async persistence, group commit for WAL writes, and asynchronous replication with 100ms lag tolerance.

**Indexing Optimization**: CREATE INDEX ON operations (document_id, timestamp) for operation replay, INDEX ON operations (user_id, timestamp) for user activity queries. Partition operations by document_id for optimal query patterns.

**Active Session Cache (Redis):**
Keeping a document's state in memory on one server for the duration of the session improves performance (no need to constantly fetch from DB)

- Real-time presence information
- Session affinity management

### 4.2 Data Models

**Document Schema:**
```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY,
    title VARCHAR(255),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    owner_id UUID,
    current_version INTEGER,
    content_snapshot JSONB
);

CREATE TABLE operations (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID,
    operation_type VARCHAR(50),
    position INTEGER,
    content TEXT,
    user_id UUID,
    timestamp TIMESTAMP,
    version_vector JSONB,
    transformed_from BIGINT[]
);
```

**Operation Log Schema Sizing**: Each operation record ~200 bytes (UUID=16, VARCHAR=50, INTEGER=4, TEXT=100, TIMESTAMP=8, JSONB=20), projecting 20GB/day for 100K active users.

### 4.3 Storage Optimization Strategies

**Snapshot Strategy:**
- Full document snapshots every 100 operations
- Incremental rebuilds from latest snapshot + operations
- Automated compression for historical snapshots
- Implement delta snapshots for large documents, storing only changes since last full snapshot to reduce storage overhead

**Compaction Algorithm**: Compact operation logs older than 7 days while preserving operations needed for conflict resolution, triggered when log size exceeds 1GB per document.

**Partitioning:**
- Documents partitioned by creation date
- Operations partitioned by document_id for query optimization
- Geographic distribution for global access patterns

## 5. Consistency Model Implementation

### 5.1 Consistency Model Specification

**Strong Eventual Consistency (SEC)**: Implements Strong Eventual Consistency (SEC) where all replicas that receive the same set of operations converge to identical state without coordination. This provides the formal guarantee that concurrent updates will converge to the same state without requiring coordination between replicas.

### 5.2 CAP Theorem Analysis

**CAP Tradeoff Selection**: Choose AP from CAP theorem - prioritize Availability and Partition tolerance over strong Consistency to maintain collaborative editing during network partitions. This allows the system to remain responsive during network issues while ensuring eventual convergence.

### 5.3 Consistency Guarantee Bounds

**Convergence Timing**: Guarantee convergence within 500ms after network partition healing, with conflict resolution completing within 100ms of receiving conflicting operations. These bounds ensure predictable behavior for users during network instability.

## 6. Partition Tolerance Design

### 6.1 Partition Detection

**Detection Algorithm**: Detect partitions using 10-second heartbeat timeout with 3-strike failure detection and exponential backoff for false positive mitigation. This prevents premature partition declarations during temporary network congestion.

### 6.2 Operation Handling During Partitions

**Queuing Strategy**: Queue operations locally with 10MB limit per client, persist to local storage, notify users when queue approaches capacity. This ensures user operations aren't lost during network partitions.

### 6.3 Partition Reconciliation

**Reconciliation Algorithm**: Use vector clock comparison to identify divergent operations, apply OT transformation to resolve conflicts, merge operation logs in causal order. This systematic approach ensures consistent state restoration when partitions heal.

## 7. Operational Concerns

### 7.1 Monitoring and Observability

**Key Performance Indicators:**
Define workload health indicators, KPIs, and performance metrics so that telemetry collection strategies reflect these targets

- Operation propagation latency (target: <100ms)
- Conflict resolution time
- Document synchronization success rate
- User session stability

**Detailed Metrics**: Operation latency P95 <100ms, P99 <200ms; Conflict resolution rate <1% of operations; WebSocket connection success >99.5%; Memory usage per server <80%; CPU utilization <75%; Database write throughput >40K ops/sec; Network bandwidth <150MB/sec.

**Monitoring Infrastructure:**

The metrics collector sends metric data to a queuing system like Kafka. Then consumers or streaming processing services such as Apache Spark process and push the data to the time-series database. This approach has several advantages: Kafka is used as a highly reliable and scalable distributed messaging platform

**Alerting Strategy:**

When health states change from healthy to degraded or unhealthy, alerting mechanisms trigger the automatic corrective measures and notifies appropriate teams

**Tiered Alerting**: Critical alerts (latency >200ms) escalate immediately, Warning alerts (latency >150ms) escalate after 5 minutes, with 15/30 minute escalation tiers.

Critical alerts include:
- Operation latency exceeding 100ms threshold
- Document synchronization failures
- WebSocket connection drops above 5%
- Database connection pool exhaustion

### 7.2 Scalability Architecture

**Horizontal Scaling Strategy:**
Many designs use a sticky routing: once a server loads a document (either from storage or from operations), it keeps that session until idle

**Sharding Strategy**: Shard by document_id using consistent hashing with virtual nodes. Each shard handles 1K active documents with automatic rebalancing when shard exceeds 80% capacity.

**Load Balancing Algorithm**: Use consistent hashing load balancer with document_id as key, ensuring all operations for same document route to same server instance.

**Auto-Scaling Thresholds**: Scale up at 80% CPU or 85% memory utilization, scale down at 40% CPU with 10-minute cooldown period.

- Load balancer with session affinity for document ownership
- Auto-scaling based on concurrent user metrics

**Geographic Distribution:**
- Multi-region deployment with document affinity
- Edge caching for static content and document snapshots
- Regional presence service instances

### 7.3 Performance Optimization

**Operation Propagation Latency Design** (Primary Priority):

**Latency Budget Breakdown**: 100ms total = 30ms network RTT + 20ms serialization + 25ms OT processing + 15ms database write + 10ms propagation buffer.

**Batching Strategy**: Adaptive batching with 10ms timeout or 50 operations per batch, whichever comes first. High-priority operations (cursor movements) bypass batching.

- Direct WebSocket message routing without intermediate queues
- In-memory operation caching for active documents
- Optimized transformation algorithm implementations
- Pre-computed transformation matrices for common operation patterns

**Network Optimization:**
- Binary protocol for operation serialization
- Delta compression for large operations
- Connection pooling and keep-alive strategies

**Protocol Efficiency Optimization**:
**Serialization Format**: Use Protocol Buffers reducing message size 60% vs JSON, with average operation message size of 80 bytes vs 200 bytes JSON.

**Compression Strategy**: Implement gzip compression with 9KB sliding window for WebSocket frames, delta compression using XOR for similar operations.

**Bandwidth Usage**: Average 2KB/sec per active user, peak 10KB/sec during heavy editing, total 200MB/sec for 100K concurrent users.

### 7.4 Memory Optimization

**Memory Usage Calculation**: 2MB per active user: 1.5MB operation buffer + 0.3MB connection state + 0.2MB document cache = 2GB total for 1K users per server.

**Operation History Pruning**: Prune operations older than 48 hours while preserving conflict resolution window of 24 hours for concurrent editing scenarios.

**Garbage Collection Strategy**: Garbage collect tombstones after 7-day safety window, triggered when memory usage exceeds 80% with background cleanup process.

### 7.5 WebSocket Connection Management

**Connection Pooling Strategy**: Use connection pools with 100 connections per pool, round-robin distribution across pools, with connection affinity based on document_id hash.

- 1,000 concurrent users per application server
- 10,000 documents per operation transformation engine
- 100,000 operations per minute per database shard

### 7.6 Fault Tolerance and Disaster Recovery

**High Availability Design:**
- Multi-master database configuration with automatic failover
- Document state reconstruction from operation logs
- Cross-region backup with 4-hour RPO

**Disaster Recovery Targets**: RTO (Recovery Time Objective) of 15 minutes for critical services, RPO (Recovery Point Objective) of 4 hours for data loss tolerance.

**Graceful Degradation Strategy**: When database is unavailable, switch to read-only mode with cached document snapshots. When transformation engine fails, buffer operations locally and process when service recovers.

**SLA Definitions**: 99.9% uptime for collaborative editing features, <100ms P95 latency for operations, <1% data loss tolerance during disasters.

**Circuit Breaker Patterns:**
- Database connection circuit breakers
- External service degradation handling
- Graceful degradation to read-only mode

**Data Consistency Guarantees:**
- Write-ahead logging for all operations
- Checksum validation for operation integrity
- Conflict resolution audit trails

### 7.7 Security and Compliance

**Access Control:**
- JWT-based authentication with refresh tokens
- Role-based document permissions (owner, editor, viewer)
- Operation-level authorization checks

**Data Protection:**
- AES-256 encryption for data at rest
- TLS 1.3 for data in transit
- PII anonymization in operation logs

### 7.8 Capacity Planning

**Predictive Model**: Use time series analysis on user growth patterns to predict scaling needs 7 days ahead, with automated scaling triggers at 80% capacity thresholds.

**Resource Integration**: Base capacity planning on calculated per-user memory usage: with 2MB per user and 16GB server capacity, each server supports 8K users (with 2GB overhead), not the previous 1K estimate.

**Scaling Thresholds:**
- 1,000 concurrent users per application server
- 10,000 documents per operation transformation engine
- 100,000 operations per minute per database shard

**Resource Requirements:**
- 16GB RAM per application server (document caching)
- 8 CPU cores per OT engine (transformation processing)
- 50TB storage per million active documents (including history)

## 8. Implementation Roadmap

### Phase 1: Core Infrastructure (Weeks 1-6)
- Basic OT engine implementation
- WebSocket gateway setup
- Primary database schema
- Basic conflict resolution

### Phase 2: Scale Optimization (Weeks 7-12)
- Operation propagation latency optimization
- Caching layer implementation  
- Monitoring and alerting setup
- Load testing and performance tuning

### Phase 3: Production Readiness (Weeks 13-16)
- Multi-region deployment
- Advanced conflict resolution
- Comprehensive monitoring
- Security hardening

This architecture prioritizes operation propagation latency as the primary constraint while ensuring the system can reliably handle 100,000 concurrent users with eventual consistency guarantees and robust operational monitoring.