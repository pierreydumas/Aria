# Token Budget Router: Implementation Strategy & Task Complexity Classification

**Goal**: goal-24f27d2f - Implement Token Budget Router for Intelligent Model Selection  
**Date**: 2026-03-10  
**Author**: Aria Blue ⚡️

---

## Executive Summary

The Token Budget Router enables Aria to dynamically select the most cost-effective model tier based on task complexity analysis. This document outlines the implementation strategy, complexity classification framework, and integration points with existing infrastructure.

**Current Model Tiers** (from models.yaml):
1. **Tier 0 (Free/Local)**: qwen3-mlx - 4B params, 128K context, fastest, zero cost
2. **Tier 1 (Free Cloud)**: trinity-free, qwen3-next-free - balanced performance
3. **Tier 2 (Premium)**: kimi - highest capability, paid

---

## Task Complexity Classification System

### Complexity Dimensions

| Dimension | Weight | Metrics |
|-----------|--------|---------|
| **Prompt Length** | 0.20 | Tokens: <500 (simple), 500-2000 (medium), >2000 (complex) |
| **Expected Output Type** | 0.25 | Single word, paragraph, structured data, code, analysis |
| **Task Category** | 0.30 | Creative, analytical, coding, conversational |
| **Reasoning Depth** | 0.15 | Factual recall, inference, multi-step reasoning |
| **Domain Specialization** | 0.10 | General knowledge, technical, domain-specific |

### Task Category Scoring Matrix

```python
TASK_COMPLEXITY_SCORES = {
    # Low complexity (Tier 0)
    "simple_chat": {"base_score": 15, "tier": 0},
    "greeting": {"base_score": 10, "tier": 0},
    "acknowledgment": {"base_score": 10, "tier": 0},
    "factual_recall": {"base_score": 20, "tier": 0},
    
    # Medium complexity (Tier 1)
    "content_drafting": {"base_score": 35, "tier": 1},
    "summarization": {"base_score": 30, "tier": 1},
    "basic_analysis": {"base_score": 40, "tier": 1},
    "explanation": {"base_score": 35, "tier": 1},
    
    # High complexity (Tier 2)
    "code_generation": {"base_score": 55, "tier": 2},
    "complex_reasoning": {"base_score": 60, "tier": 2},
    "architectural_design": {"base_score": 65, "tier": 2},
    "multi_step_analysis": {"base_score": 70, "tier": 2},
    "security_review": {"base_score": 75, "tier": 2},
}
```

### Prompt Length Multipliers

```python
LENGTH_MULTIPLIERS = {
    "short": {"range": (0, 500), "multiplier": 0.8},
    "medium": {"range": (500, 2000), "multiplier": 1.0},
    "long": {"range": (2000, 8000), "multiplier": 1.2},
    "very_long": {"range": (8000, 128000), "multiplier": 1.4},
}
```

---

## Router Algorithm

```python
def calculate_complexity_score(task_features: TaskFeatures) -> ComplexityScore:
    """
    Calculate overall complexity score (0-100) and recommended tier.
    """
    base_score = TASK_COMPLEXITY_SCORES[task_features.category]["base_score"]
    
    # Apply length multiplier
    length_mult = get_length_multiplier(task_features.prompt_tokens)
    adjusted_score = base_score * length_mult
    
    # Add reasoning depth modifier
    reasoning_bonus = task_features.reasoning_steps * 5  # +5 per step
    adjusted_score += reasoning_bonus
    
    # Domain specialization adjustment
    if task_features.domain == "technical":
        adjusted_score += 10
    elif task_features.domain == "security":
        adjusted_score += 15
    
    # Cap at 100
    final_score = min(adjusted_score, 100)
    
    # Determine tier
    if final_score < 30:
        recommended_tier = 0  # qwen3-mlx
    elif final_score < 60:
        recommended_tier = 1  # trinity-free / qwen3-next-free
    else:
        recommended_tier = 2  # kimi
    
    return ComplexityScore(
        score=final_score,
        tier=recommended_tier,
        confidence=calculate_confidence(task_features),
        reasoning=f"Category: {task_features.category}, Length: {task_features.prompt_tokens} tokens"
    )
```

---

## Budget Threshold Integration

### Dynamic Tier Adjustment Based on Spend

```python
BUDGET_THRESHOLDS = {
    "daily_limit": 10.0,  # $10/day
    "warning_levels": {
        0.50: {"action": "log", "message": "50% budget used"},
        0.70: {"action": "prefer_free", "message": "Preferring free tiers"},
        0.85: {"action": "force_free", "message": "Forcing free tiers"},
        0.95: {"action": "circuit_break", "message": "Budget critical - pausing premium"},
    }
}

def apply_budget_constraints(
    complexity_score: ComplexityScore,
    daily_spend: float,
    daily_limit: float
) -> RoutingDecision:
    """
    Adjust routing based on budget constraints.
    """
    usage_ratio = daily_spend / daily_limit
    
    # Find applicable threshold
    for threshold, config in sorted(BUDGET_THRESHOLDS["warning_levels"].items()):
        if usage_ratio >= threshold:
            if config["action"] == "force_free":
                # Force downgrade by one tier
                complexity_score.tier = max(0, complexity_score.tier - 1)
            elif config["action"] == "circuit_break":
                # Only allow tier 0
                complexity_score.tier = 0
    
    return RoutingDecision(
        selected_model=get_model_for_tier(complexity_score.tier),
        original_tier=complexity_score.tier,
        adjusted_tier=complexity_score.tier,
        budget_constrained=(usage_ratio > 0.70),
        reasoning=complexity_score.reasoning
    )
```

---

## Skill Architecture

### Core Classes

```python
@dataclass
class TaskFeatures:
    """Input features for complexity analysis."""
    prompt: str
    prompt_tokens: int
    category: str
    expected_output_type: str
    reasoning_steps: int
    domain: str
    context_history: Optional[List[Dict]] = None

@dataclass  
class ComplexityScore:
    """Output of complexity analysis."""
    score: float  # 0-100
    tier: int  # 0, 1, or 2
    confidence: float  # 0-1
    reasoning: str

@dataclass
class RoutingDecision:
    """Final routing decision."""
    selected_model: str
    original_tier: int
    adjusted_tier: int
    budget_constrained: bool
    reasoning: str
    estimated_cost: Optional[float] = None

class TaskComplexityAnalyzer:
    """Analyzes task complexity using heuristics and LLM classification."""
    
    def __init__(self):
        self.classifier_model = "qwen3-mlx"  # Fast classification
        self.heuristic_weights = HEURISTIC_WEIGHTS
    
    async def analyze(self, task: TaskFeatures) -> ComplexityScore:
        # Fast heuristic pass
        heuristic_score = self._heuristic_analysis(task)
        
        # LLM refinement for edge cases
        if heuristic_score.confidence < 0.7:
            llm_score = await self._llm_classification(task)
            return self._blend_scores(heuristic_score, llm_score)
        
        return heuristic_score

class TokenBudgetRouter:
    """Main router that combines complexity analysis with budget constraints."""
    
    def __init__(self, litellm_client, budget_monitor):
        self.analyzer = TaskComplexityAnalyzer()
        self.litellm = litellm_client
        self.budget = budget_monitor
        self.routing_history = []
    
    async def route_request(
        self,
        prompt: str,
        context: Optional[Dict] = None
    ) -> RoutingDecision:
        # 1. Extract features
        features = self._extract_features(prompt, context)
        
        # 2. Calculate complexity
        complexity = await self.analyzer.analyze(features)
        
        # 3. Get current budget status
        daily_spend = await self.budget.get_daily_spend()
        daily_limit = self.budget.daily_limit
        
        # 4. Apply budget constraints
        decision = apply_budget_constraints(complexity, daily_spend, daily_limit)
        
        # 5. Log routing decision
        self.routing_history.append({
            "timestamp": datetime.utcnow(),
            "features": features,
            "decision": decision
        })
        
        return decision
```

---

## Integration with Existing Infrastructure

### LiteLLM Proxy Integration

```python
# Route through LiteLLM with model selection
async def execute_with_routing(
    self,
    prompt: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7
) -> str:
    # Get routing decision
    decision = await self.route_request(prompt)
    
    # Call LiteLLM with selected model
    response = await self.litellm.chat_completion(
        model=decision.selected_model,
        messages=messages,
        temperature=temperature
    )
    
    # Track actual cost
    actual_cost = response.get("usage", {}).get("total_cost", 0)
    await self.budget.track_spend(actual_cost)
    
    return response["choices"][0]["message"]["content"]
```

### Model Switcher Integration

The router works alongside the existing model_switcher skill:
- `model_switcher`: Manual override and priority management
- `token_router`: Automatic intelligent selection

Priority order:
1. User explicit model selection
2. Circuit breaker forced fallback
3. Token router recommendation
4. Default model

---

## Performance Benchmarks

### Classification Accuracy Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Tier prediction accuracy | >85% | Manual review of 100 requests |
| Classification latency | <50ms | Average over 1000 requests |
| Cost savings vs always-premium | >40% | Monthly spend comparison |
| Quality degradation | <5% | User satisfaction survey |

### Expected Savings by Task Type

| Task Type | Current (always kimi) | With Router | Savings |
|-----------|----------------------|-------------|---------|
| Simple chat | $0.05/1K | $0.00/1K | 100% |
| Summarization | $0.08/1K | $0.00/1K | 100% |
| Code review | $0.12/1K | $0.00/1K (qwen3-coder) | 100% |
| Complex analysis | $0.15/1K | $0.15/1K | 0% |
| Architecture design | $0.20/1K | $0.20/1K | 0% |

---

## Implementation Phases

### Phase 1: Heuristic Router (Week 1)
- [ ] Implement TaskComplexityAnalyzer with heuristic scoring
- [ ] Create complexity classification dataset (100 sample prompts)
- [ ] Build basic TokenBudgetRouter
- [ ] Integrate with litellm_client

### Phase 2: Budget Monitoring (Week 2)
- [ ] Implement BudgetMonitor class with LiteLLM API integration
- [ ] Add threshold alerts (50%, 70%, 85%, 95%)
- [ ] Build circuit breaker for budget limits
- [ ] Create dashboard endpoint

### Phase 3: LLM Classification (Week 3)
- [ ] Add LLM-based classification for edge cases
- [ ] Implement confidence scoring
- [ ] Build training data collection pipeline
- [ ] A/B test heuristic vs LLM classification

### Phase 4: Optimization (Week 4)
- [ ] Tune weights based on real-world usage
- [ ] Add caching for repeated prompt patterns
- [ ] Implement feedback loop (success/failure tracking)
- [ ] Document and deploy

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Misclassification | Confidence threshold → escalate to higher tier |
| Budget overshoot | Conservative thresholds + real-time spend tracking |
| Quality degradation | User feedback loop + automatic tier elevation |
| Latency overhead | Fast heuristic path (<10ms) for common cases |

---

## Success Criteria

1. **Functional**: Router correctly classifies >85% of requests
2. **Economic**: Reduces daily spend by >30% without quality loss
3. **Performance**: Adds <50ms latency per request
4. **Reliability**: Zero budget overruns with circuit breaker active

---

## Next Steps

1. Create `skills/token_router/__init__.py` with core classes
2. Implement TaskComplexityAnalyzer._heuristic_analysis()
3. Build test suite with 100 classification samples
4. Integrate with existing litellm_client skill

*Generated during work cycle for goal-24f27d2f*  
*Progress contribution: +15% (research artifact with implementation strategy)*
