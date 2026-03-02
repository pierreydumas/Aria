"""
Aria Brain API — Configuration
All environment variables and service configuration in one place.
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timezone

_logger = logging.getLogger("aria.config")


def _load_stack_env_if_present() -> None:
    """Best-effort load of stacks/brain/.env into process env.

    Only fills missing keys; never overrides explicitly provided env vars.
    """
    env_path = Path(__file__).resolve().parents[2] / "stacks" / "brain" / ".env"
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as e:
        _logger.warning("Failed to load stack .env from %s: %s", env_path, e)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    _load_stack_env_if_present()
    db_user = os.getenv("DB_USER", "aria_admin")
    db_password = os.getenv("DB_PASSWORD", "admin")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "aria_warehouse")
    DATABASE_URL = (
        f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )
    logging.getLogger("aria.api").warning(
        "DATABASE_URL not set — using fallback DSN from DB_* env/defaults"
    )

# ── Networking ────────────────────────────────────────────────────────────────
DOCKER_HOST_IP = os.getenv("DOCKER_HOST_IP", "host.docker.internal")
MLX_ENABLED = os.getenv("MLX_ENABLED", "false").lower() == "true"

# ── Service discovery (name → (base_url, health_path)) ───────────────────────
SERVICE_URLS: dict[str, tuple[str, str]] = {
    "grafana":    (os.getenv("GRAFANA_URL",    "http://grafana:3000"),           "/api/health"),
    "prometheus": (os.getenv("PROMETHEUS_URL",  "http://prometheus:9090"),        "/prometheus/-/healthy"),
    "ollama":     (os.getenv("OLLAMA_URL",      f"http://{DOCKER_HOST_IP}:11434"), "/api/tags"),
    "litellm":    (os.getenv("LITELLM_URL",     "http://litellm:4000"),          "/health/liveliness"),
    "pgadmin":    (os.getenv("PGADMIN_URL",     "http://aria-pgadmin:80"),       "/"),
    "browser":    (os.getenv("BROWSER_URL", "http://aria-browser:3000"),         "/"),
    "traefik":    (os.getenv("TRAEFIK_URL",     "http://traefik:8080"),          "/api/overview"),
    "aria-web":   (os.getenv("ARIA_WEB_URL",    "http://aria-web:5000"),         "/"),
    "aria-api":   (os.getenv("ARIA_API_SELF_URL", f"http://localhost:{os.getenv('API_INTERNAL_PORT', '8000')}"), "/health"),
}

OPTIONAL_SERVICE_IDS: set[str] = {
    value.strip()
    for value in os.getenv(
        "ARIA_OPTIONAL_SERVICES",
        "grafana,prometheus,pgadmin",
    ).split(",")
    if value.strip()
}

if MLX_ENABLED:
    SERVICE_URLS["mlx"] = (
        os.getenv("MLX_URL", f"http://{DOCKER_HOST_IP}:8080"),
        "/v1/models",
    )

# ── Admin / Service control ──────────────────────────────────────────────────
ARIA_ADMIN_TOKEN = os.getenv("ARIA_ADMIN_TOKEN")
if not ARIA_ADMIN_TOKEN:
    import logging as _logging
    _logging.getLogger("aria.api").warning("ARIA_ADMIN_TOKEN not set — admin endpoints will reject all requests")
SERVICE_CONTROL_ENABLED = os.getenv(
    "ARIA_SERVICE_CONTROL_ENABLED", "false"
).lower() in {"1", "true", "yes"}

# ── LiteLLM / Providers ─────────────────────────────────────────────────────
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
MOONSHOT_KIMI_KEY  = os.getenv("MOONSHOT_KIMI_KEY", "")
OPEN_ROUTER_KEY    = os.getenv("OPEN_ROUTER_KEY", "")

# ── Startup jobs ─────────────────────────────────────────────────────────────
SKILL_BACKFILL_ON_STARTUP = os.getenv(
    "SKILL_BACKFILL_ON_STARTUP", "false"
).lower() in {"1", "true", "yes"}

# ── Filesystem paths ────────────────────────────────────────────────────────
ARIA_AGENTS_ROOT = os.getenv("ARIA_AGENTS_ROOT", "/app/agents")
ARIA_JOBS_PATH = os.getenv("ARIA_JOBS_PATH", "/app/jobs.json")

# ── Runtime ──────────────────────────────────────────────────────────────────
STARTUP_TIME = datetime.now(timezone.utc)
API_VERSION  = "3.0.0"
