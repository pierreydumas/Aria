# Knowledge Graph Caching Layer - Design Specification

## Goal
Implement a high-performance caching layer for the Aria knowledge graph to achieve 40%+ query latency reduction.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Client Query                                │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              KGCacheManager (Singleton)                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ EntityCache     │  │ TraversalCache  │  │ StatsCollector  │ │
│  │ (LRU - 1000)    │  │ (TTL - 5min)    │  │ (Metrics)       │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                            │
                    Cache Hit? ──Yes──► Return cached
                            │ No
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              PostgreSQL Knowledge Graph                          │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    Store in cache
```

## Components

### 1. KGCacheManager
Central coordinator managing all cache layers.

**Key Features:**
- Singleton pattern for system-wide consistency
- Automatic cache warming for hot entities
- Cache statistics and health monitoring
- Graceful degradation on cache failure

### 2. EntityCache (LRU)
Caches individual entity lookups by ID and name.

**Configuration:**
- Max size: 1000 entities
- Eviction: LRU (Least Recently Used)
- TTL: 10 minutes for entity data

**Cache Keys:**
- `entity:id:{uuid}` - Entity by ID
- `entity:name:{name}:{type}` - Entity by name+type

### 3. TraversalCache (Memoized)
Caches traversal query results.

**Configuration:**
- Max size: 500 traversal results
- TTL: 5 minutes (shorter due to relationship volatility)
- Key: Hash of (start_entity + depth + filters)

### 4. Invalidation Strategy
Automatic invalidation on:
- Entity create/update/delete
- Relation create/delete
- Manual cache clear API

## Implementation Plan

### Phase 1: Core Cache Module (Current Work)
- [x] Design specification
- [ ] Implement EntityCache with LRU
- [ ] Implement TraversalCache with memoization
- [ ] Build invalidation hooks

### Phase 2: Integration (Next)
- [ ] Integrate with existing KG skill
- [ ] Add cache statistics endpoint
- [ ] Performance benchmarking

### Phase 3: Optimization (Future)
- [ ] Cache warming strategies
- [ ] Predictive caching based on query patterns
- [ ] Distributed cache support (Redis)

## Expected Performance Gains

| Query Type | Without Cache | With Cache | Improvement |
|------------|--------------|------------|-------------|
| Entity by ID | ~15ms | ~0.5ms | 97% |
| Entity by name | ~25ms | ~0.5ms | 98% |
| Traversal (depth 1) | ~45ms | ~2ms | 96% |
| Traversal (depth 2) | ~120ms | ~5ms | 96% |

**Overall Target: 40%+ latency reduction**

## Files to Create

1. `skills/aria_kg_cache/__init__.py` - Main cache manager
2. `skills/aria_kg_cache/skill.json` - Skill manifest
3. `tests/test_kg_cache.py` - Unit tests

## Next Actions
1. Implement core cache classes
2. Add skill integration layer
3. Run benchmark tests
