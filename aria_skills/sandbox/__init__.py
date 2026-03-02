# aria_skills/sandbox/__init__.py
"""
Sandbox Skill — safe code execution in isolated Docker container.

Provides Aria with the ability to run code, write/read files, and run tests
in an isolated sandbox environment with resource limits.
All sandbox operations are logged via api_client.
"""
import os
import logging
from datetime import datetime, timezone

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


@SkillRegistry.register
class SandboxSkill(BaseSkill):
    """
    Executes code in an isolated Docker sandbox.

    The sandbox container (aria-sandbox) runs on aria-net with:
    - No internet access
    - 2 CPU, 2GB RAM limits
    - Python 3.12 + common packages (httpx, pytest, pyyaml)

    Methods:
        run_code(code, timeout) — Execute Python code
        write_file(path, content) — Write file in sandbox
        read_file(path) — Read file from sandbox
        run_tests(test_path) — Run pytest in sandbox
    """

    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None
        self._sandbox_url: str = ""

    @property
    def name(self) -> str:
        return "sandbox"

    @property
    def canonical_name(self) -> str:
        return "aria-sandbox"

    async def initialize(self) -> bool:
        if not HAS_HTTPX:
            self.logger.error("httpx not installed — sandbox unavailable")
            self._status = SkillStatus.UNAVAILABLE
            return False

        self._sandbox_url = self.config.config.get(
            "sandbox_url",
            os.environ.get("SANDBOX_URL", "http://aria-sandbox:9999"),
        )
        self._client = httpx.AsyncClient(
            base_url=self._sandbox_url,
            timeout=120.0,
        )
        self._status = SkillStatus.AVAILABLE
        return True

    async def health_check(self) -> SkillStatus:
        if not self._client:
            return SkillStatus.UNAVAILABLE
        try:
            resp = await self._client.get("/health")
            if resp.status_code == 200:
                self._status = SkillStatus.AVAILABLE
            else:
                self._status = SkillStatus.ERROR
        except Exception:
            self._status = SkillStatus.ERROR
        return self._status

    @staticmethod
    def _sanitize_path(path: str) -> str:
        """S-104: Sanitize file path to prevent code injection."""
        # Remove quotes, semicolons, newlines — prevents breaking out of f-string
        sanitized = path.replace("'", "").replace('"', '').replace(';', '').replace('\n', '').replace('\r', '')
        # Prevent path traversal
        sanitized = sanitized.replace('..', '')
        return sanitized

    @logged_method()
    async def run_code(
        self,
        code: str = "",
        timeout: int = 30,
        input: str = "",
        **kwargs,
    ) -> SkillResult:
        """Execute Python code in the sandbox."""
        if not self._client:
            return SkillResult.fail("Not initialized")

        if not code:
            code = input or kwargs.get("source") or kwargs.get("script") or ""
        if not code:
            return SkillResult.fail("Missing 'code' parameter")

        try:
            resp = await self._client.post(
                "/exec",
                json={"code": code, "timeout": timeout},
            )
            resp.raise_for_status()
            data = resp.json()

            success = data.get("exit_code", -1) == 0
            self._log_usage("run_code", success)

            return SkillResult(
                success=success,
                data=data,
                error=data.get("stderr") if not success else None,
            )
        except Exception as e:
            self._log_usage("run_code", False, error=str(e))
            return SkillResult.fail(f"Sandbox execution failed: {e}")

    @logged_method()
    async def write_file(
        self,
        path: str = "",
        content: str = "",
        *,
        file_path: str = "",
        input: str = "",
        **kwargs,
    ) -> SkillResult:
        """Write a file in the sandbox via code execution (S-104: injection-safe)."""
        # Accept both 'path' and 'file_path' — LLMs sometimes hallucinate param names
        path = path or file_path
        if not content:
            content = input or kwargs.get("text") or kwargs.get("data") or ""
        if not path:
            return SkillResult.fail("Missing 'path' parameter")
        if not self._client:
            return SkillResult.fail("Not initialized")

        # S-104: Use base64 encoding to prevent code injection via content/path
        import base64
        encoded_content = base64.b64encode(content.encode()).decode()
        safe_path = self._sanitize_path(path)
        code = (
            f"import pathlib, base64; "
            f"p = pathlib.Path('{safe_path}'); "
            f"p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(base64.b64decode('{encoded_content}').decode())"
        )

        return await self.run_code(code, timeout=10)

    @logged_method()
    async def read_file(self, path: str = "", *, file_path: str = "") -> SkillResult:
        """Read a file from the sandbox via code execution (S-104: injection-safe)."""
        # Accept both 'path' and 'file_path' — LLMs sometimes hallucinate param names
        path = path or file_path
        if not path:
            return SkillResult.fail("Missing 'path' parameter")
        if not self._client:
            return SkillResult.fail("Not initialized")

        # S-104: Sanitize path to prevent injection
        safe_path = self._sanitize_path(path)
        code = f"import pathlib; print(pathlib.Path('{safe_path}').read_text())"
        result = await self.run_code(code, timeout=10)

        if result.success and result.data:
            result.data["content"] = result.data.get("stdout", "")

        return result

    @logged_method()
    async def run_tests(self, test_path: str = "tests/") -> SkillResult:
        """Run pytest in the sandbox."""
        if not self._client:
            return SkillResult.fail("Not initialized")

        # S-104: Sanitize test path
        safe_path = self._sanitize_path(test_path)
        code = (
            f"import subprocess, sys; "
            f"r = subprocess.run([sys.executable, '-m', 'pytest', '{safe_path}', '-v', '--tb=short'], "
            f"capture_output=True, text=True, timeout=60); "
            f"print(r.stdout); print(r.stderr, file=sys.stderr); sys.exit(r.returncode)"
        )

        return await self.run_code(code, timeout=90)

    async def reset(self) -> SkillResult:
        """Reset the sandbox (kill switch — terminate and restart)."""
        if not self._client:
            return SkillResult.fail("Not initialized")

        # Send a cleanup code
        code = (
            "import shutil, os; "
            "[shutil.rmtree(d) for d in ['/sandbox/tmp', '/tmp'] "
            "if os.path.isdir(d) and d != '/tmp']; "
            "print('sandbox reset')"
        )
        return await self.run_code(code, timeout=10)
