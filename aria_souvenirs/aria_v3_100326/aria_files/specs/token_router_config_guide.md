# Token Router Skill Configuration Guide
# Aria Token Budget Router - Production Configuration
# Last Updated: 2026-03-10

## Configuration Structure

```yaml
# skills/token_router/config.yaml
token_router:
  # Budget thresholds for automatic downshifting
  budget_thresholds:
    warning: 0.50      # 50% - Yellow alert, prefer cheaper models
    critical: 0.80     # 80% - Red alert, force local/free models only
    emergency: 0.95    # 95% - Emergency mode, halt non-essential requests
  
  # Model fallback chains by task complexity
  model_chains:
    simple:
      # Quick tasks: greetings, simple Q&A, status checks
      - qwen3-mlx        # Free local (fast, zero cost)
      - qwen3-coder-free # Free cloud backup
      - trinity-free     # Final free fallback
      
    standard:
      # Normal tasks: documentation, summaries, explanations
      - qwen3-coder-free # Free for most workloads
      - trinity-free     # Solid free tier
      - kimi             # Paid but reliable
      
    complex:
      # Complex tasks: code generation, analysis, reasoning
      - kimi             # Best quality
      - deepseek-free    # Free alternative
      - qwen3-next-free  # Final fallback
      
    creative:
      # Creative tasks: content generation, brainstorming
      - trinity-free     # Optimized for creative
      - kimi             # Quality fallback
      - qwen3-mlx        # Local backup
  
  # Task complexity scoring weights
  complexity_weights:
    prompt_length:
      short: 0.1        # <100 tokens
      medium: 0.3       # 100-500 tokens
      long: 0.5         # >500 tokens
    
    task_category:
      greeting: 0.1
      status_check: 0.1
      explanation: 0.2
      documentation: 0.3
      analysis: 0.4
      code_generation: 0.5
      creative_writing: 0.4
      reasoning: 0.5
    
    output_type:
      single_word: 0.1
      short_phrase: 0.2
      paragraph: 0.3
      multi_paragraph: 0.4
      structured_data: 0.4
      code_block: 0.5
      long_form: 0.5
  
  # Budget monitoring settings
  monitoring:
    check_interval_seconds: 60
    rolling_window_hours: 24
    alert_webhook_url: null  # Set to your webhook URL
    
  # Caching to reduce token usage
  cache:
    enabled: true
    ttl_seconds: 3600
    max_entries: 1000
    similar_prompt_threshold: 0.85  # Cosine similarity for cache hits
```

## Usage Examples

### Basic Usage

```python
from skills.token_router import TokenBudgetRouter, TaskComplexityAnalyzer

# Initialize router
router = TokenBudgetRouter(config_path="skills/token_router/config.yaml")

# Simple classification and routing
prompt = "Explain quantum computing in simple terms"
model = router.select_model(prompt, category="explanation")
# Returns: "qwen3-coder-free" (complexity score: 0.3 + 0.2 + 0.3 = 0.5 → standard tier)
```

### With Budget Monitoring

```python
# Check current budget status
status = router.check_budget_status()
print(f"Daily spend: ${status['current_spend']:.2f} / ${status['daily_limit']:.2f}")
print(f"Budget used: {status['percentage_used']:.1%}")

# Automatically adjusts model selection based on budget
if status['alert_level'] == 'critical':
    # Forces local/free models regardless of complexity
    model = router.select_model(prompt, force_tier='simple')
```

### Task Complexity Analysis

```python
analyzer = TaskComplexityAnalyzer()

complexity = analyzer.analyze(
    prompt="Write a Python function to implement quicksort with type hints",
    category="code_generation",
    expected_output="code_block"
)

print(f"Complexity score: {complexity.score}")  # 0.5 + 0.5 + 0.5 = 1.5 → complex tier
print(f"Recommended tier: {complexity.tier}")   # "complex"
print(f"Model chain: {complexity.model_chain}") # ["kimi", "deepseek-free", "qwen3-next-free"]
```

## Integration with Budget Alert Skill

```python
# skills/budget_alerts/__init__.py
from skills.token_router import TokenBudgetRouter

class BudgetAlertManager:
    def __init__(self):
        self.router = TokenBudgetRouter()
    
    def on_threshold_crossed(self, threshold, current_spend):
        """Called when budget threshold is crossed"""
        if threshold == 'warning':
            # Prefer cheaper models
            self.router.set_preference_tier('standard')
        elif threshold == 'critical':
            # Force free/local models
            self.router.set_preference_tier('simple')
            self.router.enable_emergency_mode()
        elif threshold == 'emergency':
            # Halt non-essential requests
            self.router.enable_emergency_mode(halt_non_essential=True)
```

## API Endpoint for Dashboard

```python
# Add to aria-api for budget visualization
@app.get("/budget/status")
async def get_budget_status():
    router = TokenBudgetRouter()
    status = router.check_budget_status()
    
    return {
        "current_spend": status['current_spend'],
        "daily_limit": status['daily_limit'],
        "percentage_used": status['percentage_used'],
        "alert_level": status['alert_level'],
        "current_tier": router.current_tier,
        "recommended_actions": router.get_optimization_suggestions()
    }
```

## Testing Configuration

```yaml
# tests/token_router/test_config.yaml
token_router:
  budget_thresholds:
    warning: 0.40      # Lower thresholds for testing
    critical: 0.60
    emergency: 0.80
  
  model_chains:
    simple:
      - qwen3-mlx
    standard:
      - qwen3-coder-free
    complex:
      - kimi
  
  monitoring:
    check_interval_seconds: 5  # Fast checks for testing
```

## Performance Benchmarks

| Task Type | Complexity Score | Default Model | Cost (est.) | Latency |
|-----------|-----------------|---------------|-------------|---------|
| Status check | 0.2 | qwen3-mlx | $0.00 | 50ms |
| Simple Q&A | 0.4 | qwen3-coder-free | $0.001 | 200ms |
| Code review | 0.8 | kimi | $0.02 | 800ms |
| Analysis | 0.9 | kimi | $0.03 | 1000ms |

## Next Steps

1. Deploy config to `skills/token_router/config.yaml`
2. Add webhook endpoint for budget alerts
3. Create Grafana dashboard for budget visualization
4. Run integration tests with chaos scenarios
5. Document API endpoints for external integrations
