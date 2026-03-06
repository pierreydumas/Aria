#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Aria Brain Stack — First-Run Setup Script (macOS / Linux)
# Creates .env from .env.example with required secrets generated.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

AUTO=false
if [[ "${1:-}" == "--auto" ]]; then
    AUTO=true
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_DIR="$REPO_ROOT/stacks/brain"
ENV_EXAMPLE="$STACK_DIR/.env.example"
ENV_FILE="$STACK_DIR/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

banner() {
    echo -e "${CYAN}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║       🦀 Aria Brain — First Run 🦀       ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
}

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*"; }

generate_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
        || openssl rand -base64 32 | tr -d '/+=' | head -c 43
}

# ── Pre-flight checks ────────────────────────────────────────

banner

# Check Docker
if ! command -v docker &>/dev/null; then
    err "Docker is not installed. Please install Docker first."
    err "  macOS: https://docs.docker.com/desktop/install/mac-install/"
    err "  Linux: https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker info &>/dev/null; then
    err "Docker daemon is not running. Please start Docker Desktop or the Docker service."
    exit 1
fi

info "Docker detected: $(docker --version)"

# Check docker compose
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
else
    err "Docker Compose not found. Please install Docker Compose."
    exit 1
fi

info "Compose detected: $($COMPOSE_CMD version 2>/dev/null || echo 'available')"

# Check for Ollama (optional)
if command -v ollama &>/dev/null; then
    info "Ollama detected: $(ollama --version 2>/dev/null || echo 'available')"
else
    warn "Ollama not found — local models won't be available."
    warn "  Install: https://ollama.com/download"
fi

# ── .env Setup ────────────────────────────────────────────────

if [ ! -f "$ENV_EXAMPLE" ]; then
    err "Cannot find $ENV_EXAMPLE"
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    if [[ "$AUTO" == "true" ]]; then
        info ".env already exists — skipping auto-bootstrap."
        exit 0
    fi
    warn ".env already exists at $ENV_FILE"
    read -rp "Overwrite? (y/N) " choice
    if [[ ! "$choice" =~ ^[Yy]$ ]]; then
        info "Keeping existing .env. Exiting."
        exit 0
    fi
    cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
    info "Backed up existing .env"
fi

cp "$ENV_EXAMPLE" "$ENV_FILE"
info "Created .env from .env.example"

# ── Generate required secrets ─────────────────────────────────

info "Generating secrets..."

DB_PASS=$(generate_secret)
WEB_KEY=$(generate_secret)
LITELLM_KEY="sk-aria-$(generate_secret)"
GRAFANA_PASS=$(generate_secret)
PGADMIN_PASS=$(generate_secret)
API_KEY=$(generate_secret)
ADMIN_KEY=$(generate_secret)

# Use sed to fill in required values
if [[ "$OSTYPE" == "darwin"* ]]; then
    SED_I="sed -i ''"
else
    SED_I="sed -i"
fi

fill_env() {
    local key="$1" val="$2"
    # Replace "KEY=" (empty) with "KEY=value"
    eval "$SED_I 's|^${key}=$|${key}=${val}|' \"$ENV_FILE\""
}

fill_env "DB_PASSWORD" "$DB_PASS"
fill_env "WEB_SECRET_KEY" "$WEB_KEY"
fill_env "LITELLM_MASTER_KEY" "$LITELLM_KEY"
fill_env "GRAFANA_PASSWORD" "$GRAFANA_PASS"
fill_env "PGADMIN_PASSWORD" "$PGADMIN_PASS"
fill_env "ARIA_API_KEY" "$API_KEY"
fill_env "ARIA_ADMIN_KEY" "$ADMIN_KEY"

ADMIN_TOKEN=$(generate_secret)
BROWSER_TOKEN=$(generate_secret)
fill_env "ARIA_ADMIN_TOKEN" "$ADMIN_TOKEN"
fill_env "BROWSERLESS_TOKEN" "$BROWSER_TOKEN"

info "Required secrets generated and written to .env"
# In --auto mode skip port randomization (keep .env.example port defaults)
if [[ "$AUTO" == "true" ]]; then
    info "Auto-bootstrap complete — using default ports from .env.example."
    info "Run scripts/first-run.sh interactively to randomize ports."
    exit 0
fi
# ── Randomize host-exposed ports ──────────────────────────────
# Each service gets a random high port (20000-60000) to avoid conflicts.

info "Randomizing host-exposed ports..."

random_port() {
    python3 -c "import random; print(random.randint(20000, 60000))" 2>/dev/null \
        || echo $(( RANDOM % 40000 + 20000 ))
}

ARIA_API_PORT=$(random_port)
ARIA_WEB_PORT=$(random_port)
LITELLM_PORT=$(random_port)
PGADMIN_PORT=$(random_port)
BROWSERLESS_PORT=$(random_port)
TOR_SOCKS_PORT=$(random_port)
TOR_CONTROL_PORT=$(random_port)
TRAEFIK_HTTP_PORT=$(random_port)
TRAEFIK_HTTPS_PORT=$(random_port)
TRAEFIK_DASH_PORT=$(random_port)
PROMETHEUS_PORT=$(random_port)
GRAFANA_PORT=$(random_port)
JAEGER_UI_PORT=$(random_port)
JAEGER_OTLP_GRPC_PORT=$(random_port)
SANDBOX_PORT=$(random_port)

# Overwrite the default port values (not empty, so use direct sed)
set_port() {
    local key="$1" val="$2"
    eval "$SED_I 's|^${key}=.*|${key}=${val}|' \"$ENV_FILE\""
}

set_port "ARIA_API_PORT" "$ARIA_API_PORT"
set_port "ARIA_WEB_PORT" "$ARIA_WEB_PORT"
set_port "LITELLM_PORT" "$LITELLM_PORT"
set_port "PGADMIN_PORT" "$PGADMIN_PORT"
set_port "BROWSERLESS_PORT" "$BROWSERLESS_PORT"
set_port "TOR_SOCKS_PORT" "$TOR_SOCKS_PORT"
set_port "TOR_CONTROL_PORT" "$TOR_CONTROL_PORT"
set_port "TRAEFIK_HTTP_PORT" "$TRAEFIK_HTTP_PORT"
set_port "TRAEFIK_HTTPS_PORT" "$TRAEFIK_HTTPS_PORT"
set_port "TRAEFIK_DASH_PORT" "$TRAEFIK_DASH_PORT"
set_port "PROMETHEUS_PORT" "$PROMETHEUS_PORT"
set_port "GRAFANA_PORT" "$GRAFANA_PORT"
set_port "JAEGER_UI_PORT" "$JAEGER_UI_PORT"
set_port "JAEGER_OTLP_GRPC_PORT" "$JAEGER_OTLP_GRPC_PORT"
set_port "SANDBOX_PORT" "$SANDBOX_PORT"

info "Host ports randomized (no conflicts with existing services)"

# ── Optional: prompt for API keys ─────────────────────────────

echo ""
echo -e "${CYAN}Optional API Keys${NC} (press Enter to skip)"
echo "These can be added to .env later."
echo ""

read -rp "OpenRouter API Key (sk-or-v1-...): " OR_KEY
if [ -n "$OR_KEY" ]; then
    fill_env "OPEN_ROUTER_KEY" "$OR_KEY"
    info "OpenRouter key saved"
fi

read -rp "Moonshot/Kimi API Key: " KIMI_KEY
if [ -n "$KIMI_KEY" ]; then
    fill_env "MOONSHOT_KIMI_KEY" "$KIMI_KEY"
    info "Moonshot key saved"
fi

# ── Summary ───────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Setup complete!                                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  .env location:  $ENV_FILE"
echo ""
echo "  Generated credentials:"
echo "    DB_PASSWORD       = ${DB_PASS:0:8}..."
echo "    WEB_SECRET_KEY    = ${WEB_KEY:0:8}..."
echo "    LITELLM_MASTER_KEY= ${LITELLM_KEY:0:15}..."
echo "    ARIA_API_KEY      = ${API_KEY:0:8}..."
echo "    ARIA_ADMIN_KEY    = ${ADMIN_KEY:0:8}..."
echo "    GRAFANA_PASSWORD  = ${GRAFANA_PASS:0:8}..."
echo "    PGADMIN_PASSWORD  = ${PGADMIN_PASS:0:8}..."
echo ""
echo "  Randomized ports:"
echo "    API:       http://localhost:${ARIA_API_PORT}"
echo "    Web UI:    http://localhost:${ARIA_WEB_PORT}"
echo "    LiteLLM:   http://localhost:${LITELLM_PORT}"
echo "    Traefik:   http://localhost:${TRAEFIK_HTTP_PORT} (HTTP)"
echo "               https://localhost:${TRAEFIK_HTTPS_PORT} (HTTPS)"
echo ""
echo "  Next steps:"
echo "    1. Review/edit:   nano $ENV_FILE"
echo "    2. Build stack:   cd $STACK_DIR && docker compose build"
echo "    3. Start stack:   cd $STACK_DIR && docker compose up -d"
echo "    4. Open web UI:   http://localhost:${TRAEFIK_HTTP_PORT}"
echo "    5. Open API docs: http://localhost:${ARIA_API_PORT}/docs"
echo ""
