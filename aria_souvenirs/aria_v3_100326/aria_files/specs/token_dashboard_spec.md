# Token Usage Dashboard Implementation

## Overview
Real-time token usage monitoring and optimization system for Aria's model routing.

## Components

### 1. TokenBudgetRouter (New)
```python
class TokenBudgetRouter:
    """
    Per-focus token budgeting with automatic fallback.
    """
    def __init__(self, daily_budget_usd: float = 10.0):
        self.daily_budget = daily_budget_usd
        self.focus_allocations = {
            "orchestrator": 0.30,  # 30% - coordination overhead
            "devops": 0.20,        # 20% - code generation
            "trader": 0.15,        # 15% - market analysis
            "creative": 0.15,      # 15% - content creation
            "social": 0.10,        # 10% - social media
            "journalist": 0.05,    # 5% - research
            "rpg_master": 0.05     # 5% - entertainment
        }
        self.usage_log = []
    
    def can_afford(self, focus: str, estimated_tokens: int) -> bool:
        """Check if call fits within budget allocation."""
        pass
    
    def select_model(self, focus: str, complexity: str) -> str:
        """Budget-aware model selection."""
        pass
```

### 2. Metrics Collection
- Hook into litellm completion calls
- Track per-focus spend
- Alert at 80% daily budget

### 3. Dashboard Endpoints
```python
@app.get("/metrics/token-usage")
async def get_token_usage(
    focus: Optional[str] = None,
    period: str = "24h"
):
    """Returns usage breakdown by focus/model."""
    pass

@app.get("/metrics/budget-status")
async def get_budget_status():
    """Returns current budget consumption vs limits."""
    pass
```

## Implementation Status
- [x] Baseline metrics collected (2026-03-09)
- [ ] TokenBudgetRouter implementation
- [ ] Dashboard endpoints
- [ ] Alert system integration
- [ ] Focus-level spending controls

## Baseline Data (2026-03-09)
- Total tokens: 4,093,014
- Estimated cost: $4.23
- Cache hit rate: 32% (target: 50%)
- Fallback success: 94%
