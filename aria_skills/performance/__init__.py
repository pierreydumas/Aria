# aria_skills/performance.py
"""
Performance logging skill.

Tracks and logs Aria's performance metrics.
Persists via REST API (TICKET-12: eliminate in-memory stubs).
"""
from datetime import datetime, timezone
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry


@SkillRegistry.register
class PerformanceSkill(BaseSkill):
    """
    Performance logging and tracking.
    
    Records successes, failures, and improvement areas.
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._logs: list[dict] = []  # fallback cache
        self._api = None
    
    @property
    def name(self) -> str:
        return "performance"
    
    async def initialize(self) -> bool:
        """Initialize performance skill."""
        self._api = await get_api_client()
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Performance skill initialized (API-backed)")
        return True
    
    async def close(self):
        """Cleanup (shared API client is managed by api_client module)."""
        self._api = None
    
    async def health_check(self) -> SkillStatus:
        """Check availability."""
        return self._status
    
    @logged_method()
    async def log_review(
        self,
        period: str,
        successes: list[str],
        failures: list[str],
        improvements: list[str],
    ) -> SkillResult:
        """
        Log a performance review.
        
        Args:
            period: Review period (e.g., "2024-01-15")
            successes: Things that went well
            failures: Things that didn't work
            improvements: Areas to improve
            
        Returns:
            SkillResult with log ID
        """
        log = {
            "period": period,
            "successes": successes,
            "failures": failures,
            "improvements": improvements,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            result = await self._api.post("/performance", data=log)
            if not result:
                raise Exception(result.error)
            api_data = result.data
            return SkillResult.ok(api_data if api_data else log)
        except Exception as e:
            self.logger.warning(f"API log_review failed, using fallback: {e}")
            log["id"] = f"perf_{len(self._logs) + 1}"
            self._logs.append(log)
            return SkillResult.ok(log)
    
    @logged_method()
    async def get_reviews(self, limit: int = 10) -> SkillResult:
        """Get recent performance reviews."""
        try:
            result = await self._api.get("/performance", params={"limit": limit})
            if not result:
                raise Exception(result.error)
            api_data = result.data
            if isinstance(api_data, list):
                return SkillResult.ok({"reviews": api_data[-limit:], "total": len(api_data)})
            return SkillResult.ok(api_data)
        except Exception as e:
            self.logger.warning(f"API get_reviews failed, using fallback: {e}")
            return SkillResult.ok({
                "reviews": self._logs[-limit:],
                "total": len(self._logs),
            })
    
    @logged_method()
    async def get_improvement_summary(self) -> SkillResult:
        """Summarize improvement areas across reviews."""
        try:
            result = await self._api.get("/performance")
            if not result:
                raise Exception(result.error)
            api_data = result.data
            logs = api_data if isinstance(api_data, list) else api_data.get("reviews", [])
        except Exception as e:
            self.logger.warning(f"API get_improvement_summary failed, using fallback: {e}")
            logs = self._logs
        
        all_improvements = []
        for log in logs:
            all_improvements.extend(log.get("improvements", []))
        
        # Count frequency
        counts = {}
        for item in all_improvements:
            counts[item] = counts.get(item, 0) + 1
        
        sorted_improvements = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        
        return SkillResult.ok({
            "top_improvements": sorted_improvements[:10],
            "total_reviews": len(logs),
        })
    
    @logged_method()
    async def get_metrics(self, **kwargs) -> SkillResult:
        """Get skill usage metrics as a SkillResult (async-safe override)."""
        return SkillResult.ok(super().get_metrics(**kwargs))
