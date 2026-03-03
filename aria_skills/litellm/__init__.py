# aria_skills/litellm_skill.py
"""
LiteLLM proxy management skill.

Manages connection to LiteLLM proxy for multi-model support.
"""
import os
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


@SkillRegistry.register
class LiteLLMSkill(BaseSkill):
    """
    LiteLLM proxy interface.
    
    Config:
        proxy_url: URL of LiteLLM proxy
        api_key: API key if required
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._client: "httpx.AsyncClient" | None = None
        self._proxy_url: str = ""
    
    @property
    def name(self) -> str:
        return "litellm"
    
    async def initialize(self) -> bool:
        """Initialize LiteLLM client."""
        if not HAS_HTTPX:
            self.logger.error("httpx not installed")
            self._status = SkillStatus.UNAVAILABLE
            return False
        
        self._proxy_url = self.config.config.get(
            "proxy_url",
            os.environ.get("LITELLM_URL", os.environ.get("LITELLM_PROXY_URL", "http://litellm:4000"))
        ).rstrip("/")
        
        api_key = self.config.config.get(
            "api_key",
            os.environ.get("LITELLM_API_KEY", os.environ.get("LITELLM_MASTER_KEY", ""))
        )
        
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        self._client = httpx.AsyncClient(
            base_url=self._proxy_url,
            timeout=120,
            headers=headers,
        )
        
        self._status = SkillStatus.AVAILABLE
        self.logger.info(f"LiteLLM client initialized: {self._proxy_url}")
        return True
    
    async def health_check(self) -> SkillStatus:
        """Check LiteLLM proxy connectivity."""
        if not self._client:
            self._status = SkillStatus.UNAVAILABLE
            return self._status
        
        try:
            resp = await self._client.get("/health")
            self._status = SkillStatus.AVAILABLE if resp.status_code == 200 else SkillStatus.ERROR
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            self._status = SkillStatus.ERROR
        
        return self._status
    
    async def list_models(self) -> SkillResult:
        """Get available models from proxy."""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to list models: {e}")
    
    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> SkillResult:
        """
        Send chat completion request.
        
        Args:
            model: Model ID
            messages: Chat messages
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
            
        Returns:
            SkillResult with completion
        """
        try:
            metadata: dict[str, Any] = {
                "source": "aria_skills.litellm",
            }
            agent_id = (
                os.environ.get("ARIA_AGENT_ID")
                or os.environ.get("AGENT_ID")
            )
            aria_session_id = (
                os.environ.get("ARIA_SESSION_ID")
                or os.environ.get("SESSION_ID")
            )
            if agent_id:
                metadata["agent_id"] = agent_id
            if aria_session_id:
                metadata["aria_session_id"] = aria_session_id

            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "metadata": metadata,
            }
            if aria_session_id:
                payload["session_id"] = aria_session_id

            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Chat completion failed: {e}")
