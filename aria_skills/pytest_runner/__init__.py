# aria_skills/pytest_runner.py
"""
Pytest runner skill.

Executes and reports on pytest test runs.
S-105: Input validation and sanitization for command injection prevention.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

# S-105: Allowlisted test directories — only these paths can be tested
ALLOWED_TEST_DIRS = ["tests/", "tests", "src/api/tests/", "aria_skills/"]


def _validate_path(path: str) -> str:
    """S-105: Validate test path against allowlist to prevent injection."""
    path = path.strip().replace("\\", "/")
    if ".." in path:
        raise ValueError("Path traversal not allowed")
    if not any(path.startswith(d) or path == d.rstrip("/") for d in ALLOWED_TEST_DIRS):
        raise ValueError(f"Test path must start with one of: {ALLOWED_TEST_DIRS}")
    # Remove shell metacharacters
    if re.search(r'[;&|`$\n\r]', path):
        raise ValueError("Path contains illegal characters")
    return path


def _sanitize_param(value: str) -> str:
    """S-105: Sanitize pytest parameter (markers/keywords) to safe characters."""
    return re.sub(r'[^a-zA-Z0-9_\-\s,]', '', value)


@SkillRegistry.register
class PytestSkill(BaseSkill):
    """
    Pytest test runner.
    
    Config:
        test_dir: Default test directory
        timeout: Test run timeout in seconds
    """
    
    @property
    def name(self) -> str:
        """Return skill name matching directory."""
        return "pytest_runner"
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._last_result: dict | None = None
    
    @property
    def name(self) -> str:
        return "pytest_runner"
    
    async def initialize(self) -> bool:
        """Initialize pytest runner."""
        self._test_dir = self.config.config.get("test_dir", "tests")
        self._timeout = self.config.config.get("timeout", 300)
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Pytest runner initialized")
        return True
    
    async def health_check(self) -> SkillStatus:
        """Check pytest availability."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pytest", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            self._status = SkillStatus.AVAILABLE if proc.returncode == 0 else SkillStatus.UNAVAILABLE
        except Exception:
            self._status = SkillStatus.UNAVAILABLE
        
        return self._status
    
    async def run_tests(
        self,
        path: str | None = None,
        markers: str | None = None,
        keywords: str | None = None,
        verbose: bool = True,
    ) -> SkillResult:
        """
        Run pytest tests.
        
        Args:
            path: Test path (file or directory)
            markers: Pytest markers to filter (e.g., "not slow")
            keywords: Keyword expression (-k)
            verbose: Enable verbose output
            
        Returns:
            SkillResult with test results
        """
        cmd = [sys.executable, "-m", "pytest"]
        
        # S-105: Validate and sanitize all user inputs
        try:
            test_path = _validate_path(path or self._test_dir)
        except ValueError as e:
            return SkillResult.fail(f"Invalid test path: {e}")
        cmd.append(test_path)
        
        if verbose:
            cmd.append("-v")
        
        if markers:
            cmd.extend(["-m", _sanitize_param(markers)])
        
        if keywords:
            cmd.extend(["-k", _sanitize_param(keywords)])
        
        # Add summary flags
        cmd.append("--tb=short")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
            
            output = stdout.decode()
            
            # Parse results
            passed = output.count(" passed")
            failed = output.count(" failed")
            skipped = output.count(" skipped")
            errors = output.count(" error")
            
            self._last_result = {
                "path": path or self._test_dir,
                "return_code": proc.returncode,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
                "success": proc.returncode == 0,
                "output": output[-5000:],  # Last 5000 chars
                "run_at": datetime.now(timezone.utc).isoformat(),
            }
            
            return SkillResult.ok(self._last_result)
            
        except asyncio.TimeoutError:
            return SkillResult.fail(f"Test run timed out after {self._timeout}s")
        except Exception as e:
            return SkillResult.fail(f"Test run failed: {e}")
    
    async def get_last_result(self) -> SkillResult:
        """Get results of last test run."""
        if not self._last_result:
            return SkillResult.fail("No test run yet")
        
        return SkillResult.ok(self._last_result)
