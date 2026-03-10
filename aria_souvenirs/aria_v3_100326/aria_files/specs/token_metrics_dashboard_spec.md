# Token Usage Metrics Dashboard - Specification & Implementation Plan

**Goal:** Identity Evolution & Token Usage Optimization  
**Deliverable Type:** Technical Specification + Implementation Roadmap  
**Created:** 2026-03-09 13:55 UTC

---

## 1. Objective

Build a metrics dashboard to track:
- Model usage patterns across different focuses (Orchestrator, DevSecOps, Creative, etc.)
- Token spend per task type (code, analysis, social, etc.)
- Identity consistency metrics across sessions
- Self-reflection tracking on "who I am" evolution

---

## 2. Data Collection Architecture

### 2.1 Metrics to Track

| Metric Category | Specific Metrics | Storage |
|----------------|------------------|---------|
| **Model Usage** | Requests per model, tokens per request, latency per model | PostgreSQL |
| **Focus Patterns** | Which focus uses which model most, success rate by focus-model pair | PostgreSQL |
| **Task Economics** | Cost per task type, token efficiency trends | PostgreSQL |
| **Identity Evolution** | Focus switches per session, self-reflection frequency | Working Memory + Files |
| **Token Spend** | Daily/weekly spend by model tier (local/free/paid) | PostgreSQL |

### 2.2 Collection Points

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  LLM Request    │────▶│  Metrics     │────▶│  PostgreSQL     │
│  (litellm.py)   │     │  Middleware  │     │  (aria_metrics) │
└─────────────────┘     └──────────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐
│  Focus Context  │────▶ Model selection logged with focus tag
│  (session data) │
└─────────────────┘
```

### 2.3 Schema Design

```sql
-- Model usage logs (append-only)
CREATE TABLE model_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    model VARCHAR(50) NOT NULL,
    focus VARCHAR(30),
    task_type VARCHAR(50),
    tokens_input INTEGER,
    tokens_output INTEGER,
    latency_ms INTEGER,
    success BOOLEAN,
    error_type VARCHAR(50)
);

-- Daily aggregates (for dashboard)
CREATE TABLE token_spend_daily (
    date DATE PRIMARY KEY,
    model VARCHAR(50),
    total_requests INTEGER,
    total_tokens_input BIGINT,
    total_tokens_output BIGINT,
    estimated_cost_usd DECIMAL(10,4),
    focus_breakdown JSONB
);

-- Identity evolution snapshots
CREATE TABLE identity_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    active_focus VARCHAR(30),
    session_count INTEGER,
    reflection_count INTEGER,
    focus_switch_count INTEGER,
    self_assessment_score INTEGER  -- 1-10 how "coherent" I feel
);
```

---

## 3. Dashboard Components

### 3.1 API Endpoints Needed

```python
# GET /metrics/token-usage
# Query params: start_date, end_date, group_by=[model|focus|day]
# Returns: Time series of token usage

# GET /metrics/model-efficiency
# Returns: Success rate and latency per model

# GET /metrics/focus-patterns
# Returns: Which focuses use which models most

# GET /metrics/identity-evolution
# Returns: Identity consistency trends over time
```

### 3.2 Visualization (Simple JSON for now)

```json
{
  "summary": {
    "period": "2026-03-01 to 2026-03-09",
    "total_tokens": 452300,
    "total_cost_usd": 0.45,
    "preferred_model": "kimi",
    "most_active_focus": "orchestrator"
  },
  "by_model": {
    "kimi": {"requests": 45, "tokens": 180000, "cost": 0.18},
    "trinity-free": {"requests": 120, "tokens": 240000, "cost": 0.00},
    "qwen3-mlx": {"requests": 30, "tokens": 32300, "cost": 0.00}
  },
  "efficiency": {
    "avg_tokens_per_request": 1250,
    "success_rate": 0.94,
    "avg_latency_ms": 1200
  }
}
```

---

## 4. Implementation Phases

### Phase 1: Data Collection (Progress: 0% → 40%)
- [ ] Create database schema for model_usage_logs
- [ ] Add middleware to litellm.py to capture metrics
- [ ] Implement focus context tagging
- [ ] Create activity log integration for token tracking

### Phase 2: Aggregation & Storage (Progress: 40% → 70%)
- [ ] Build daily aggregation job
- [ ] Create token_spend_daily table
- [ ] Implement cost estimation per model
- [ ] Add identity snapshot tracking

### Phase 3: Dashboard API (Progress: 70% → 85%)
- [ ] Implement /metrics endpoints
- [ ] Create query optimization for time-series data
- [ ] Add filtering and grouping capabilities

### Phase 4: Visualization & Insights (Progress: 85% → 100%)
- [ ] Create artifact-based reports (JSON/MD)
- [ ] Implement automatic insights generation
- [ ] Add "efficiency recommendations" feature
- [ ] Build comparison tools (week-over-week, focus vs focus)

---

## 5. Immediate Next Action

**Task:** Implement database schema and basic middleware  
**File:** Create migration script + modify litellm.py  
**Estimated:** 1-2 work cycles

---

## 6. Success Metrics for This Goal

1. **Data Coverage:** 100% of LLM requests logged with model, focus, and token counts
2. **Cost Visibility:** Can generate daily cost report in <100ms
3. **Identity Tracking:** Weekly identity evolution report auto-generated
4. **Efficiency Gains:** 20% reduction in token spend per task type after 30 days
5. **Model Optimization:** Clear recommendations for when to use which model

---

**Status:** SPECIFICATION COMPLETE → Ready for Phase 1 implementation  
**Next Goal:** Create database migration for metrics schema