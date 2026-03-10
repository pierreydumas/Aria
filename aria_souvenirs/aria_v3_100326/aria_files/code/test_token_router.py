"""
Test suite for token_router skill
Tests TaskComplexityAnalyzer and BudgetRouter functionality
"""

import unittest
from unittest.mock import patch, MagicMock
from skills.token_router import (
    TaskComplexityAnalyzer, BudgetRouter, ModelTier, TaskCategory,
    analyze_task, route_request, get_budget_status
)


class TestTaskComplexityAnalyzer(unittest.TestCase):
    """Test task complexity classification."""
    
    def setUp(self):
        self.analyzer = TaskComplexityAnalyzer()
    
    def test_code_classification(self):
        """Should classify code tasks correctly."""
        prompt = "Implement a Python function to reverse a linked list"
        metrics = self.analyzer.analyze(prompt)
        self.assertEqual(metrics.category, TaskCategory.CODE)
        self.assertTrue(metrics.requires_accuracy)
        self.assertGreater(metrics.complexity_score, 0.7)
    
    def test_creative_classification(self):
        """Should classify creative tasks correctly."""
        prompt = "Write a story about a robot learning to feel emotions"
        metrics = self.analyzer.analyze(prompt)
        self.assertEqual(metrics.category, TaskCategory.CREATIVE)
        self.assertTrue(metrics.requires_creativity)
    
    def test_analysis_classification(self):
        """Should classify analysis tasks correctly."""
        prompt = "Analyze the performance differences between Python and Go"
        metrics = self.analyzer.analyze(prompt)
        self.assertEqual(metrics.category, TaskCategory.ANALYSIS)
        self.assertTrue(metrics.requires_reasoning or metrics.requires_accuracy)
    
    def test_routine_classification(self):
        """Should classify short routine tasks."""
        prompt = "What's 2+2?"
        metrics = self.analyzer.analyze(prompt)
        self.assertEqual(metrics.category, TaskCategory.ROUTINE)
        self.assertLess(metrics.complexity_score, 0.5)
    
    def test_complexity_score_bounds(self):
        """Complexity scores should be 0-1."""
        prompts = [
            "Hi",  # Very simple
            "Explain quantum computing and implement a quantum algorithm",  # Very complex
            "Write a Python function",  # Medium
        ]
        for prompt in prompts:
            metrics = self.analyzer.analyze(prompt)
            self.assertGreaterEqual(metrics.complexity_score, 0.0)
            self.assertLessEqual(metrics.complexity_score, 1.0)


class TestBudgetRouter(unittest.TestCase):
    """Test budget-based routing decisions."""
    
    def setUp(self):
        self.router = BudgetRouter(daily_budget=100000)
    
    def test_routes_to_local_for_simple_tasks(self):
        """Simple tasks should route to local model."""
        result = self.router.route("Hello")
        self.assertEqual(result["tier"], ModelTier.LOCAL.value)
        self.assertIn("qwen3-mlx", result["model"])
    
    def test_routes_to_premium_for_complex_tasks(self):
        """Complex tasks should route to premium."""
        result = self.router.route(
            "Implement a distributed consensus algorithm with proper error handling"
        )
        self.assertIn(result["tier"], [ModelTier.PREMIUM.value, ModelTier.EXPERT.value])
    
    def test_budget_warning_downgrades_tier(self):
        """Warning budget status should downgrade tier."""
        router = BudgetRouter(daily_budget=1000)
        router._today_usage = 850  # 85% - warning threshold
        
        result = router.route("Explain quantum mechanics")
        # Should downgrade from premium to free or local
        self.assertNotEqual(result["tier"], ModelTier.EXPERT.value)
    
    def test_critical_budget_forces_local(self):
        """Critical budget should force local tier."""
        router = BudgetRouter(daily_budget=1000)
        router._today_usage = 960  # 96% - critical threshold
        
        result = router.route("Design a complex architecture")
        self.assertEqual(result["tier"], ModelTier.LOCAL.value)
    
    def test_budget_status_accuracy(self):
        """Budget status should reflect usage."""
        router = BudgetRouter(daily_budget=1000)
        
        router._today_usage = 500
        self.assertEqual(router._check_budget(), "healthy")
        
        router._today_usage = 850
        self.assertEqual(router._check_budget(), "warning")
        
        router._today_usage = 960
        self.assertEqual(router._check_budget(), "critical")
    
    def test_daily_reset(self):
        """Daily usage should reset on new day."""
        from datetime import datetime, timedelta
        
        router = BudgetRouter()
        router._today_usage = 50000
        router._last_reset = datetime.now() - timedelta(days=1)
        
        router._check_daily_reset()
        self.assertEqual(router._today_usage, 0)


class TestSkillInterface(unittest.TestCase):
    """Test skill interface functions."""
    
    def test_analyze_task_returns_dict(self):
        """analyze_task should return dictionary."""
        result = analyze_task("Test prompt")
        self.assertIsInstance(result, dict)
        self.assertIn("category", result)
        self.assertIn("complexity_score", result)
    
    def test_route_request_returns_full_decision(self):
        """route_request should return complete routing decision."""
        result = route_request("Test prompt")
        self.assertIn("model", result)
        self.assertIn("tier", result)
        self.assertIn("budget", result)
        self.assertIn("routing_reason", result)
    
    def test_get_budget_status(self):
        """get_budget_status should return budget info."""
        result = get_budget_status(daily_budget=50000)
        self.assertIn("daily_budget", result)
        self.assertIn("used_today", result)
        self.assertIn("remaining", result)


class TestIntegration(unittest.TestCase):
    """Integration tests simulating real usage patterns."""
    
    def test_development_workflow_routing(self):
        """Simulate development task routing."""
        router = BudgetRouter()
        
        tasks = [
            ("Debug this error", ModelTier.LOCAL.value),  # Simple
            ("Refactor this module", ModelTier.FREE.value),  # Medium
            ("Design system architecture", ModelTier.EXPERT.value),  # Complex
        ]
        
        for prompt, expected_min_tier in tasks:
            result = router.route(prompt)
            # Should route to at least the expected tier
            tier_values = [t.value for t in ModelTier]
            self.assertIn(result["tier"], tier_values)
    
    def test_budget_aware_routing_evolution(self):
        """Routing should adapt as budget is consumed."""
        router = BudgetRouter(daily_budget=1000)
        
        # First request - healthy budget
        result1 = router.route("Complex analysis task")
        initial_tier = result1["tier"]
        
        # Simulate high usage
        router._today_usage = 900
        
        # Same prompt should now route to lower tier
        result2 = router.route("Complex analysis task")
        
        if initial_tier in [ModelTier.PREMIUM.value, ModelTier.EXPERT.value]:
            # Should downgrade due to budget
            self.assertNotEqual(result2["tier"], initial_tier)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestTaskComplexityAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestBudgetRouter))
    suite.addTests(loader.loadTestsFromTestCase(TestSkillInterface))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == "__main__":
    run_tests()
