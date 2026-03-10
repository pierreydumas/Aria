# Token Router Integration Guide

## Overview
The `token_router` skill provides intelligent model selection based on task complexity and budget constraints. It automatically routes requests to the most cost-effective model that can handle the task.

## Quick Start

```python
from skills.token_router import route_request, get_budget_status

# Route a request
result = route_request("Write a Python function to sort a list")
print(f"Selected model: {result['model']}")
print(f"Tier: {result['tier']}")
print(f"Reason: {result['routing_reason']}")
```

## Configuration

### Default Budget Settings
- **Daily Budget**: 100,000 tokens
- **Warning Threshold**: 80% (80,000 tokens)
- **Critical Threshold**: 95% (95,000 tokens)

### Custom Budget
```python
from skills.token_router import BudgetRouter

router = BudgetRouter(
    daily_budget=50000,
    warning_threshold=0.7,
    critical_threshold=0.9
)

result = router.route("Your prompt here")
```

## Model Tiers

| Tier | Models | Use Case |
|------|--------|----------|
| LOCAL | qwen3-mlx | Simple queries, routine tasks |
| FREE | trinity-free, qwen3-next-free | Standard tasks, quick responses |
| PREMIUM | kimi | Complex reasoning, accuracy needed |
| EXPERT | deepseek-free, kimi | Expert-level tasks, maximum quality |

## Task Categories

### Code Tasks
Routed to: EXPERT/PREMIUM (requires accuracy)

Keywords detected:
- implement, refactor, debug, test, optimize
- architecture, design pattern, algorithm

### Analysis Tasks
Routed to: PREMIUM/EXPERT (requires reasoning)

Keywords detected:
- analyze, compare, evaluate, synthesize
- research, examine, investigate

### Creative Tasks
Routed to: FREE/PREMIUM

Keywords detected:
- write, create, design, story
- imagine, brainstorm, narrative

### Routine Tasks
Routed to: LOCAL (short, simple queries)

Example: "What's the time?", "Summarize in 3 bullets"

## Budget Management

### Automatic Downshifting
When budget reaches thresholds, the router automatically downgrades:
- **Warning (80%)**: Premium → Free
- **Critical (95%)**: All → Local

### Budget Status Check
```python
status = get_budget_status()
print(f"Used: {status['used_today']}/{status['daily_budget']}")
print(f"Status: {status['usage_ratio']:.1%}")
```

## Integration with Aria

### Usage in Skills
```python
from skills.token_router import BudgetRouter

class MySkill:
    def __init__(self):
        self.router = BudgetRouter(daily_budget=50000)
    
    def process(self, prompt):
        # Get routing decision
        route = self.router.route(prompt)
        
        # Use selected model
        model = route['model']
        # ... make LLM call with selected model ...
        
        return result
```

### Monitoring
```python
# Get routing history
history = router.get_routing_history(limit=10)
for route in history:
    print(f"{route['timestamp']}: {route['model']} for {route['category']}")

# Check current budget
budget = router.get_budget_status()
if budget['usage_ratio'] > 0.8:
    print("Warning: Approaching daily budget limit")
```

## Testing

Run the test suite:
```bash
cd /app
python -m pytest skills/token_router/test_token_router.py -v
```

Or run directly:
```bash
python skills/token_router/test_token_router.py
```

## Best Practices

1. **Set appropriate budgets**: Match daily budget to expected usage
2. **Monitor warnings**: Take action when budget warnings trigger
3. **Use force_tier sparingly**: Let the router decide for most cases
4. **Review routing history**: Analyze patterns to optimize budgets

## Troubleshooting

### Issue: All requests routing to LOCAL
- Check budget status - may have hit critical threshold
- Verify prompt complexity - short prompts default to routine

### Issue: Complex tasks routed to FREE tier
- Budget may be in warning state (auto-downshift)
- Force tier manually if needed: `router.route(prompt, force_tier=ModelTier.EXPERT)`

### Issue: Budget not resetting
- Daily reset happens automatically based on date change
- Manual reset: `router._today_usage = 0`
