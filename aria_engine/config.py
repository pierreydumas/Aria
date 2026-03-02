"""Engine configuration — all settings from environment + models.yaml."""

import os
from typing import Any
from pathlib import Path

try:
    from pydantic_settings import BaseSettings
    from pydantic import field_validator, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

if HAS_PYDANTIC:
    class EngineConfig(BaseSettings):
        """Runtime configuration for Aria Engine (validated via Pydantic)."""

        model_config = {"env_prefix": "", "extra": "ignore"}

        # Database
        database_url: str = Field(
            default="postgresql://admin:admin@localhost:5432/aria_warehouse",
            alias="DATABASE_URL",
        )

        # LLM
        litellm_base_url: str = Field(
            default="http://litellm:4000/v1",
            alias="LITELLM_BASE_URL",
        )
        litellm_master_key: str = Field(default="", alias="LITELLM_MASTER_KEY")
        default_model: str = "kimi"
        default_temperature: float = 0.7
        default_max_tokens: int = 4096

        # Agent pool
        max_concurrent_agents: int = 5
        agent_context_limit: int = 50

        # Scheduler
        scheduler_enabled: bool = True
        heartbeat_interval_seconds: int = 3600

        # Paths
        models_yaml_path: str = str(
            Path(__file__).parent.parent / "aria_models" / "models.yaml"
        )
        soul_path: str = str(
            Path(__file__).parent.parent / "aria_mind" / "soul"
        )
        memories_path: str = Field(
            default=str(Path(__file__).parent.parent / "aria_memories"),
            alias="ARIA_MEMORIES_PATH",
        )

        # WebSocket
        ws_ping_interval: int = 30
        ws_ping_timeout: int = 10

        # Database pool
        db_pool_size: int = 10
        db_max_overflow: int = 20

        # Debug
        debug: bool = False

        @field_validator("database_url")
        @classmethod
        def validate_database_url(cls, v: str) -> str:
            if "admin:admin" in v and os.environ.get("ARIA_ENV", "dev") == "production":
                raise ValueError("Default database credentials detected in production!")
            if not v.startswith(("postgresql://", "postgresql+asyncpg://", "sqlite://")):
                raise ValueError(f"Invalid database URL scheme: {v}")
            return v

        @field_validator("default_temperature")
        @classmethod
        def validate_temperature(cls, v: float) -> float:
            if not 0.0 <= v <= 2.0:
                raise ValueError(f"Temperature must be 0.0-2.0, got {v}")
            return v

        @field_validator("default_max_tokens")
        @classmethod
        def validate_max_tokens(cls, v: int) -> int:
            if v < 1 or v > 200000:
                raise ValueError(f"max_tokens must be 1-200000, got {v}")
            return v

        @field_validator("max_concurrent_agents")
        @classmethod
        def validate_max_agents(cls, v: int) -> int:
            if v < 1 or v > 50:
                raise ValueError(f"max_concurrent_agents must be 1-50, got {v}")
            return v

        @classmethod
        def from_env(cls) -> "EngineConfig":
            """Create config from environment variables."""
            return cls()

else:
    # Fallback: plain dataclass if pydantic-settings not installed
    from dataclasses import dataclass, field

    @dataclass
    class EngineConfig:  # type: ignore[no-redef]
        """Runtime configuration for Aria Engine (unvalidated fallback)."""

        # Database
        database_url: str = field(default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://admin:admin@localhost:5432/aria_warehouse"
        ))

        # LLM
        litellm_base_url: str = field(default_factory=lambda: os.environ.get(
            "LITELLM_BASE_URL", "http://litellm:4000/v1"
        ))
        litellm_master_key: str = field(default_factory=lambda: os.environ.get(
            "LITELLM_MASTER_KEY", ""
        ))
        default_model: str = "kimi"
        default_temperature: float = 0.7
        default_max_tokens: int = 4096

        # Agent pool
        max_concurrent_agents: int = 5
        agent_context_limit: int = 50

        # Scheduler
        scheduler_enabled: bool = True
        heartbeat_interval_seconds: int = 3600

        # Paths
        models_yaml_path: str = field(default_factory=lambda: str(
            Path(__file__).parent.parent / "aria_models" / "models.yaml"
        ))
        soul_path: str = field(default_factory=lambda: str(
            Path(__file__).parent.parent / "aria_mind" / "soul"
        ))
        memories_path: str = field(default_factory=lambda: os.environ.get(
            "ARIA_MEMORIES_PATH", str(Path(__file__).parent.parent / "aria_memories")
        ))

        # WebSocket
        ws_ping_interval: int = 30
        ws_ping_timeout: int = 10

        # Database pool
        db_pool_size: int = 10
        db_max_overflow: int = 20

        # Debug
        debug: bool = field(default_factory=lambda: os.environ.get(
            "ENGINE_DEBUG", "false"
        ).lower() in ("true", "1", "yes"))

        @classmethod
        def from_env(cls) -> "EngineConfig":
            """Create config from environment variables."""
            return cls()
