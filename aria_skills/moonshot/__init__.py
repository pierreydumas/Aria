# aria_skills/moonshot/__init__.py
"""
Moonshot (Kimi) LLM interface skill.

Split from aria_skills/llm/ per Skill Standard v2 naming convention.
"""
import json
import os
from datetime import datetime
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# Load default Moonshot model name from models.yaml (single source of truth)
try:
    from aria_models.loader import get_task_model
    _DEFAULT_MOONSHOT_MODEL = get_task_model("moonshot_default")
except Exception:
    _DEFAULT_MOONSHOT_MODEL = ""


@SkillRegistry.register
class MoonshotSkill(BaseSkill):
    """
    Moonshot (Kimi) LLM interface.
    
    Config:
        api_key: Moonshot API key (or env:MOONSHOT_API_KEY)
        model: Model name (default: kimi)
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._client: "httpx.AsyncClient" | None = None
        self._model: str = ""
    
    @property
    def name(self) -> str:
        return "moonshot"
    
    async def initialize(self) -> bool:
        """Initialize Moonshot client."""
        if not HAS_HTTPX:
            self.logger.error("httpx not installed")
            self._status = SkillStatus.UNAVAILABLE
            return False
        
        api_key = self._get_env_value("api_key")
        if not api_key:
            api_key = os.environ.get("MOONSHOT_API_KEY")
        
        if not api_key:
            self.logger.warning("No Moonshot API key configured")
            self._status = SkillStatus.UNAVAILABLE
            return False
        
        self._model = self.config.config.get("model", _DEFAULT_MOONSHOT_MODEL)
        
        self._client = httpx.AsyncClient(
            base_url="https://api.moonshot.ai/v1",
            timeout=120,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        
        self._status = SkillStatus.AVAILABLE
        self.logger.info(f"Moonshot initialized with model: {self._model}")
        return True
    
    async def health_check(self) -> SkillStatus:
        """Check Moonshot API connectivity."""
        if not self._client:
            self._status = SkillStatus.UNAVAILABLE
            return self._status
        
        try:
            resp = await self._client.get("/models")
            self._status = SkillStatus.AVAILABLE if resp.status_code == 200 else SkillStatus.ERROR
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            self._status = SkillStatus.ERROR
        
        return self._status
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> SkillResult:
        """
        Send chat completion request.
        
        Args:
            messages: List of {"role": "user/assistant", "content": "..."}
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum response tokens
            system_prompt: Optional system message
            
        Returns:
            SkillResult with response
        """
        if not self._client:
            return SkillResult.fail("Moonshot not initialized")
        
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        try:
            resp = await self._client.post("/chat/completions", json={
                "model": self._model,
                "messages": full_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
            resp.raise_for_status()
            
            data = resp.json()
            self._log_usage("chat", True)
            
            return SkillResult.ok({
                "content": data["choices"][0]["message"]["content"],
                "model": self._model,
                "usage": data.get("usage", {}),
                "finish_reason": data["choices"][0].get("finish_reason"),
            })
            
        except Exception as e:
            self._log_usage("chat", False)
            return SkillResult.fail(f"Chat failed: {e}")
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
