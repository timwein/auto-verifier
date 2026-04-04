# System Design Document: Real-Time Collaborative Document Editor

## Executive Summary

This document outlines the architectural design for a real-time collaborative document editor capable of supporting 100,000 concurrent users. 
The system targets low latency for collaboration (<100ms typical)
 while maintaining 
conflict-free merging and eventual consistency
. The design prioritizes operation propagation latency over protocol efficiency optimizations to ensure optimal user experience at scale.

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
 to achieve 
low latency with changes propagating to others in milliseconds
. The system supports graceful fallback to HTTP long polling when WebSocket connections are unavailable.

## 2. CRDT vs Operational Transformation Trade-offs

### 2.1 Analysis Framework


CRDT is like OT in following a general transformation approach, but achieves the same transformation indirectly, in contrast to OT direct transformation approach
. Both approaches ensure eventual consistency but differ significantly in implementation complexity and operational characteristics.

### 2.2 Operational Transformation (OT) Selection

**Rationale for OT:**
- 
Google Docs handles 2+ billion documents with real-time collaboration. They chose OT because the server must see every operation anyway for access control, rendering, and storage. Having a central server transform operations adds minimal latency overhead (< 5ms) but dramatically simplifies the data model

- 
OT is efficient with operations usually small, and the server controls ordering

- 
Documents stay compact—no heavy metadata per character


**OT Advantages:**
- **Latency Optimization**: Central authority enables sub-100ms operation propagation
- **Storage Efficiency**: No tombstone data or exponential metadata growth
- **Mature Implementation**: 
OT was invented for supporting real-time co-editors in the late 1980s and has evolved to become a collection of core techniques widely used in today's working co-editors


### 2.3 CRDT Limitations at Scale


When it comes to more advanced structures such as rich text editing, the crux of the problem with CRDTs is user intent
. Additional concerns include:

- **Memory Overhead**: 
CRDTs do not remove characters... They grow forever... This is one of CRDT's real costs

- **Rich Text Complexity**: 
With a CRDT implementation, when the collaborating user's cursor is in the "after" section, the application of bold recreates the text node and the user has a poor experience


## 3. Conflict Resolution Strategy

### 3.3 Multi-Layered Conflict Resolution

The system implements a sophisticated conflict resolution strategy combining:

1. **Operation Transformation**: 
Operational Transformation is a widely used technique in real-time collaborative systems. It allows operations (insertions, deletions, etc.) to be transformed based on the context of other concurrent operations


2. **Intent Preservation**: 
The CCR approach is able to create new results from conflicts, generate alternative solutions based on collective effects of conflict operations, and support users to choose suitable conflict solutions


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

**Active Session Cache (Redis):**
- 
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

### 4.3 Storage Optimization Strategies

**Snapshot Strategy:**
- Full document snapshots every 100 operations
- Incremental rebuilds from latest snapshot + operations
- Automated compression for historical snapshots

**Partitioning:**
- Documents partitioned by creation date
- Operations partitioned by document_id for query optimization
- Geographic distribution for global access patterns

## 5. Operational Concerns

### 5.1 Monitoring and Observability

**Key Performance Indicators:**
- 
Define workload health indicators, KPIs, and performance metrics so that telemetry collection strategies reflect these targets

- Operation propagation latency (target: <100ms)
- Conflict resolution time
- Document synchronization success rate
- User session stability

**Monitoring Infrastructure:**

The metrics collector sends metric data to a queuing system like Kafka. Then consumers or streaming processing services such as Apache Spark process and push the data to the time-series database. This approach has several advantages: Kafka is used as a highly reliable and scalable distributed messaging platform


**Alerting Strategy:**

When health states change from healthy to degraded or unhealthy, alerting mechanisms trigger the automatic corrective measures and notifies appropriate teams


Critical alerts include:
- Operation latency exceeding 100ms threshold
- Document synchronization failures
- WebSocket connection drops above 5%
- Database connection pool exhaustion

### 5.2 Scalability Architecture

**Horizontal Scaling Strategy:**
- 
Many designs use a sticky routing: once a server loads a document (either from storage or from operations), it keeps that session until idle

- Load balancer with session affinity for document ownership
- Auto-scaling based on concurrent user metrics

**Geographic Distribution:**
- Multi-region deployment with document affinity
- Edge caching for static content and document snapshots
- Regional presence service instances

### 5.3 Performance Optimization

**Operation Propagation Latency Design** (Primary Priority):
- Direct WebSocket message routing without intermediate queues
- In-memory operation caching for active documents
- Optimized transformation algorithm implementations
- Pre-computed transformation matrices for common operation patterns

**Network Optimization:**
- Binary protocol for operation serialization
- Delta compression for large operations
- Connection pooling and keep-alive strategies

### 5.4 Fault Tolerance and Disaster Recovery

**High Availability Design:**
- Multi-master database configuration with automatic failover
- Document state reconstruction from operation logs
- Cross-region backup with 4-hour RPO

**Circuit Breaker Patterns:**
- Database connection circuit breakers
- External service degradation handling
- Graceful degradation to read-only mode

**Data Consistency Guarantees:**
- Write-ahead logging for all operations
- Checksum validation for operation integrity
- Conflict resolution audit trails

### 5.5 Security and Compliance

**Access Control:**
- JWT-based authentication with refresh tokens
- Role-based document permissions (owner, editor, viewer)
- Operation-level authorization checks

**Data Protection:**
- AES-256 encryption for data at rest
- TLS 1.3 for data in transit
- PII anonymization in operation logs

### 5.6 Capacity Planning

**Scaling Thresholds:**
- 1,000 concurrent users per application server
- 10,000 documents per operation transformation engine
- 100,000 operations per minute per database shard

**Resource Requirements:**
- 16GB RAM per application server (document caching)
- 8 CPU cores per OT engine (transformation processing)
- 50TB storage per million active documents (including history)

## 6. Implementation Roadmap

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