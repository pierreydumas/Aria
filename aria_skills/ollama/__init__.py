# aria_skills/ollama/__init__.py
"""
Ollama local LLM interface skill.

Split from aria_skills/llm/ per Skill Standard v2 naming convention.
"""
import os

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# Load default Ollama model name from models.yaml (single source of truth)
try:
    from aria_models.loader import get_task_model
    _DEFAULT_OLLAMA_MODEL = get_task_model("ollama_default")
except Exception:
    _DEFAULT_OLLAMA_MODEL = ""


@SkillRegistry.register
class OllamaSkill(BaseSkill):
    """
    Ollama local LLM interface.
    
    Config:
        host: Ollama server URL (default: http://localhost:11434)
        model: Model name (default: llama2)
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._client: "httpx.AsyncClient" | None = None
        self._model: str = ""
        self._host: str = ""
    
    @property
    def name(self) -> str:
        return "ollama"
    
    async def initialize(self) -> bool:
        """Initialize Ollama client."""
        if not HAS_HTTPX:
            self.logger.error("httpx not installed")
            self._status = SkillStatus.UNAVAILABLE
            return False
        
        self._host = self.config.config.get(
            "host", 
            os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        ).rstrip("/")
        
        self._model = self.config.config.get("model", _DEFAULT_OLLAMA_MODEL)
        
        self._client = httpx.AsyncClient(
            base_url=self._host,
            timeout=300,  # Longer timeout for local inference
        )
        
        # Verify connectivity
        try:
            resp = await self._client.get("/api/tags")
            if resp.status_code == 200:
                self._status = SkillStatus.AVAILABLE
                self.logger.info(f"Ollama initialized: {self._host} / {self._model}")
                return True
        except Exception as e:
            self.logger.warning(f"Ollama not available: {e}")
        
        self._status = SkillStatus.UNAVAILABLE
        return False
    
    async def health_check(self) -> SkillStatus:
        """Check Ollama connectivity."""
        if not self._client:
            self._status = SkillStatus.UNAVAILABLE
            return self._status
        
        try:
            resp = await self._client.get("/api/tags")
            self._status = SkillStatus.AVAILABLE if resp.status_code == 200 else SkillStatus.ERROR
        except Exception:
            self._status = SkillStatus.ERROR
        
        return self._status
    
    async def list_models(self) -> SkillResult:
        """List available Ollama models."""
        if not self._client:
            return SkillResult.fail("Ollama not initialized")
        
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            
            return SkillResult.ok({
                "models": [m["name"] for m in data.get("models", [])],
                "current": self._model,
            })
        except Exception as e:
            return SkillResult.fail(f"Failed to list models: {e}")
    
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> SkillResult:
        """
        Generate text completion.
        
        Args:
            prompt: Input prompt
            system: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            
        Returns:
            SkillResult with generated text
        """
        if not self._client:
            return SkillResult.fail("Ollama not initialized")
        
        try:
            payload = {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            
            if system:
                payload["system"] = system
            
            resp = await self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            
            data = resp.json()
            self._log_usage("generate", True)
            
            return SkillResult.ok({
                "response": data.get("response", ""),
                "model": self._model,
                "done": data.get("done", True),
                "context_length": data.get("context", 0),
            })
            
        except Exception as e:
            self._log_usage("generate", False)
            return SkillResult.fail(f"Generation failed: {e}")
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> SkillResult:
        """
        Chat completion.
        
        Args:
            messages: List of {"role": "user/assistant/system", "content": "..."}
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            
        Returns:
            SkillResult with response
        """
        if not self._client:
            return SkillResult.fail("Ollama not initialized")
        
        try:
            resp = await self._client.post("/api/chat", json={
                "model": self._model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            })
            resp.raise_for_status()
            
            data = resp.json()
            self._log_usage("chat", True)
            
            return SkillResult.ok({
                "content": data.get("message", {}).get("content", ""),
                "model": self._model,
                "done": data.get("done", True),
            })
            
        except Exception as e:
            self._log_usage("chat", False)
            return SkillResult.fail(f"Chat failed: {e}")
    
    async def set_model(self, model: str) -> SkillResult:
        """Switch to a different model."""
        self._model = model
        return SkillResult.ok({"model": model, "message": f"Switched to {model}"})
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
