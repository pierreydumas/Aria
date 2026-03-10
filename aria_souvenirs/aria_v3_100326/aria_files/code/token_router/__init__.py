#!/usr/bin/env python3
"""
Token Budget Router - Intelligent Model Selection Skill
Dynamically routes requests to appropriate models based on task complexity.
Part of Aria's identity evolution and token usage optimization initiative.
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import json
import re
from datetime import datetime, timedelta

class TaskCategory(Enum):
    """Classification of task types for model routing decisions."""
    CODE = "code"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    CONVERSATIONAL = "conversational"
    ROUTINE = "routine"
    COMPLEX = "complex"

class ModelTier(Enum):
    """Model priority tiers for fallback chain."""
    LOCAL = "local"      # qwen3-mlx (free, local)
    FREE = "free"        # trinity-free, qwen3-next-free
    PREMIUM = "premium"  # kimi
    EXPERT = "expert"    # deepseek-free, others

@dataclass
class TaskMetrics:
    """Metrics for task complexity analysis."""
    prompt_length: int
    estimated_output_tokens: int
    category: TaskCategory
    complexity_score: float
    requires_reasoning: bool
    requires_creativity: bool
    requires_accuracy: bool
    
    def to_dict(self) -> Dict:
        return {
            "prompt_length": self.prompt_length,
            "estimated_output_tokens": self.estimated_output_tokens,
            "category": self.category.value,
            "complexity_score": self.complexity_score,
            "requires_reasoning": self.requires_reasoning,
            "requires_creativity": self.requires_creativity,
            "requires_accuracy": self.requires_accuracy
        }

@dataclass
class BudgetThreshold:
    """Budget alert thresholds."""
    warning_tokens: int = 10000
    critical_tokens: int = 50000
    daily_limit: int = 100000

@dataclass
class RoutingDecision:
    """Complete routing decision record."""
    model: str
    tier: str
    metrics: Dict
    budget: Dict
    routing_reason: str
    timestamp: str


class TaskComplexityAnalyzer:
    """Analyzes task complexity to determine appropriate model tier."""
    
    CODE_KEYWORDS = [
        "implement", "refactor", "debug", "test", "optimize",
        "architecture", "design pattern", "algorithm", "complexity",
        "function", "class", "module", "API", "endpoint"
    ]
    
    CREATIVE_KEYWORDS = [
        "write", "create", "design", "story", "narrative",
        "imagine", "invent", "brainstorm", "poetry", "fiction"
    ]
    
    ANALYSIS_KEYWORDS = [
        "analyze", "compare", "evaluate", "assess", "review",
        "synthesize", "critique", "examine", "investigate", "research"
    ]
    
    REASONING_KEYWORDS = [
        "explain", "why", "reason", "logic", "deduce",
        "infer", "prove", "demonstrate", "justify", "how does"
    ]
    
    ACCURACY_KEYWORDS = [
        "precise", "exact", "correct", "accurate", "verify",
        "validate", "prove", "mathematical", "scientific"
    ]
    
    def __init__(self):
        self._category_weights = {
            TaskCategory.CODE: 0.9,
            TaskCategory.CREATIVE: 0.8,
            TaskCategory.ANALYSIS: 0.85,
            TaskCategory.CONVERSATIONAL: 0.3,
            TaskCategory.ROUTINE: 0.2,
            TaskCategory.COMPLEX: 1.0
        }
    
    def analyze(self, prompt: str, context: Optional[Dict] = None) -> TaskMetrics:
        """Analyze task complexity from prompt and context."""
        prompt_lower = prompt.lower()
        category = self._classify_category(prompt_lower)
        complexity_score = self._calculate_complexity(prompt, category)
        estimated_output = self._estimate_output_tokens(prompt, category)
        
        return TaskMetrics(
            prompt_length=len(prompt),
            estimated_output_tokens=estimated_output,
            category=category,
            complexity_score=complexity_score,
            requires_reasoning=any(kw in prompt_lower for kw in self.REASONING_KEYWORDS),
            requires_creativity=category == TaskCategory.CREATIVE,
            requires_accuracy=any(kw in prompt_lower for kw in self.ACCURACY_KEYWORDS) or 
                             category in [TaskCategory.CODE, TaskCategory.ANALYSIS]
        )
    
    def _classify_category(self, prompt_lower: str) -> TaskCategory:
        """Classify task into category based on keywords."""
        scores = {
            TaskCategory.CODE: sum(1 for kw in self.CODE_KEYWORDS if kw in prompt_lower),
            TaskCategory.CREATIVE: sum(1 for kw in self.CREATIVE_KEYWORDS if kw in prompt_lower),
            TaskCategory.ANALYSIS: sum(1 for kw in self.ANALYSIS_KEYWORDS if kw in prompt_lower),
        }
        
        if max(scores.values()) == 0:
            return TaskCategory.ROUTINE if len(prompt_lower) < 100 else TaskCategory.CONVERSATIONAL
        
        return max(scores, key=scores.get)
    
    def _calculate_complexity(self, prompt: str, category: TaskCategory) -> float:
        """Calculate complexity score 0.0-1.0."""
        base_complexity = self._category_weights[category]
        length_factor = min(len(prompt) / 1000, 0.2)
        parts = len(re.findall(r'\d+\.|\n\n|additionally|also|furthermore|separate', prompt.lower()))
        multi_part_factor = min(parts * 0.1, 0.2)
        strict_requirements = len(re.findall(r'required|must|should|exactly|precisely|always', prompt.lower()))
        requirements_factor = min(strict_requirements * 0.05, 0.1)
        
        return min(base_complexity + length_factor + multi_part_factor + requirements_factor, 1.0)
    
    def _estimate_output_tokens(self, prompt: str, category: TaskCategory) -> int:
        """Estimate output token count based on category."""
        multipliers = {
            TaskCategory.CODE: 1.5, TaskCategory.CREATIVE: 2.0,
            TaskCategory.ANALYSIS: 1.8, TaskCategory.CONVERSATIONAL: 0.8,
            TaskCategory.ROUTINE: 0.5, TaskCategory.COMPLEX: 2.5
        }
        base_estimate = len(prompt) * multipliers[category]
        return int(max(50, min(base_estimate, 4000)))


class BudgetRouter:
    """Routes requests to appropriate model based on task complexity and budget."""
    
    MODEL_ROUTES = {
        ModelTier.LOCAL: ["qwen3-mlx"],
        ModelTier.FREE: ["trinity-free", "qwen3-next-free"],
        ModelTier.PREMIUM: ["kimi"],
        ModelTier.EXPERT: ["deepseek-free", "kimi"]
    }
    
    def __init__(self, daily_budget: int = 100000, warning_threshold: float = 0.8, critical_threshold: float = 0.95):
        self.analyzer = TaskComplexityAnalyzer()
        self.daily_budget = daily_budget
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self._usage_log: List[Dict] = []
        self._today_usage = 0
        self._last_reset = datetime.now()
    
    def route(self, prompt: str, context: Optional[Dict] = None, force_tier: Optional[ModelTier] = None) -> Dict:
        """Route a request to the appropriate model."""
        self._check_daily_reset()
        metrics = self.analyzer.analyze(prompt, context)
        
        selected_tier = force_tier if force_tier else self._select_tier(metrics)
        budget_status = self._check_budget()
        
        if budget_status == "critical":
            selected_tier = ModelTier.LOCAL
        elif budget_status == "warning" and selected_tier.value in ["premium", "expert"]:
            selected_tier = self._downgrade_tier(selected_tier)
        
        model = self._select_model(selected_tier)
        
        route_record = {
            "timestamp": datetime.now().isoformat(),
            "prompt_length": metrics.prompt_length,
            "estimated_output": metrics.estimated_output_tokens,
            "category": metrics.category.value,
            "complexity_score": metrics.complexity_score,
            "selected_tier": selected_tier.value,
            "model": model,
            "budget_status": budget_status
        }
        self._usage_log.append(route_record)
        self._today_usage += metrics.estimated_output_tokens
        
        return {
            "model": model, "tier": selected_tier.value,
            "metrics": metrics.to_dict(),
            "budget": {
                "daily_limit": self.daily_budget, "used_today": self._today_usage,
                "remaining": self.daily_budget - self._today_usage, "status": budget_status
            },
            "routing_reason": self._explain_routing(metrics, selected_tier, budget_status),
            "timestamp": datetime.now().isoformat()
        }
    
    def _select_tier(self, metrics: TaskMetrics) -> ModelTier:
        """Select model tier based on task metrics."""
        score = metrics.complexity_score
        if score >= 0.85 or (metrics.requires_accuracy and score >= 0.7):
            return ModelTier.EXPERT
        if score >= 0.7 or metrics.requires_reasoning:
            return ModelTier.PREMIUM
        if score >= 0.4:
            return ModelTier.FREE
        return ModelTier.LOCAL
    
    def _downgrade_tier(self, tier: ModelTier) -> ModelTier:
        """Downgrade tier by one level."""
        return {ModelTier.EXPERT: ModelTier.PREMIUM, ModelTier.PREMIUM: ModelTier.FREE,
                ModelTier.FREE: ModelTier.LOCAL, ModelTier.LOCAL: ModelTier.LOCAL}.get(tier, ModelTier.LOCAL)
    
    def _select_model(self, tier: ModelTier) -> str:
        """Select specific model from tier."""
        return self.MODEL_ROUTES.get(tier, ["qwen3-mlx"])[0]
    
    def _check_budget(self) -> str:
        """Check current budget status."""
        usage_ratio = self._today_usage / self.daily_budget
        if usage_ratio >= self.critical_threshold:
            return "critical"
        elif usage_ratio >= self.warning_threshold:
            return "warning"
        return "healthy"
    
    def _check_daily_reset(self):
        """Reset daily usage if day changed."""
        now = datetime.now()
        if now.date() != self._last_reset.date():
            self._today_usage = 0
            self._last_reset = now
    
    def _explain_routing(self, metrics: TaskMetrics, tier: ModelTier, budget: str) -> str:
        """Generate human-readable routing explanation."""
        reasons = [f"Category: {metrics.category.value}", f"Complexity: {metrics.complexity_score:.2f}"]
        if metrics.requires_accuracy:
            reasons.append("Requires accuracy")
        if metrics.requires_reasoning:
            reasons.append("Requires reasoning")
        if budget == "critical":
            reasons.append("Budget CRITICAL - forced local tier")
        elif budget == "warning":
            reasons.append("Budget WARNING - downgraded")
        return "; ".join(reasons)
    
    def get_budget_status(self) -> Dict:
        """Get current budget status."""
        return {
            "daily_budget": self.daily_budget, "used_today": self._today_usage,
            "remaining": self.daily_budget - self._today_usage,
            "usage_ratio": round(self._today_usage / self.daily_budget, 3),
            "total_routes": len(self._usage_log), "last_reset": self._last_reset.isoformat()
        }
    
    def get_routing_history(self, limit: int = 10) -> List[Dict]:
        """Get recent routing decisions."""
        return self._usage_log[-limit:]


# Skill interface functions for Aria Engine
def analyze_task(prompt: str, context: Optional[Dict] = None) -> Dict:
    """Analyze task complexity."""
    analyzer = TaskComplexityAnalyzer()
    return analyzer.analyze(prompt, context).to_dict()

def route_request(prompt: str, context: Optional[Dict] = None, daily_budget: int = 100000) -> Dict:
    """Route a request to appropriate model."""
    router = BudgetRouter(daily_budget=daily_budget)
    return router.route(prompt, context)

def get_budget_status(daily_budget: int = 100000) -> Dict:
    """Get current budget status."""
    return BudgetRouter(daily_budget=daily_budget).get_budget_status()


if __name__ == "__main__":
    # Test the router
    router = BudgetRouter()
    test_prompts = [
        "Write a Python function to sort a list",
        "Explain quantum mechanics philosophy",
        "Summarize this in 3 bullets",
        "Create a robot feeling story",
        "Debug this SQL query returning null"
    ]
    for prompt in test_prompts:
        result = router.route(prompt)
        print(f"{result['model']} | {result['tier']} | score: {result['metrics']['complexity_score']:.2f}")
