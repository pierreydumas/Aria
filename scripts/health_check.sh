#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:$PATH

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
STACK_ENV_FILE="$ROOT_DIR/stacks/brain/.env"

if [[ -f "$STACK_ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    value="${value%\r}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "$key=$value"
  done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$STACK_ENV_FILE")
fi

API_PORT="${ARIA_API_PORT:-8000}"
WEB_PORT="${ARIA_WEB_PORT:-5050}"

echo "=== WEB PAGES ==="
for page in / /dashboard /activities /thoughts /memories /records /search /services /models /wallets /goals /heartbeat /knowledge /social /performance /security /operations /sessions /working-memory /skills /soul /model-usage /rate-limits /api-key-rotations; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${WEB_PORT}${page}" || true)
  echo "  ${page} -> ${code}"
done
# NOTE: /heartbeat is the health monitoring page (no /health web route exists)

echo "=== API ENDPOINTS ==="
for ep in /api/health /api/status /api/stats /api/activities /api/thoughts /api/memories /api/goals /api/hourly-goals /api/sessions /api/skills /api/social /api/knowledge-graph /api/working-memory/context /api/rate-limits /api/security-events /api/schedule /api/litellm/models /api/litellm/spend /api/models/config /api/admin/soul /api/records/thoughts; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${API_PORT}${ep}" || true)
  echo "  ${ep} -> ${code}"
done
# NOTE: /api/knowledge-graph is the correct path (not /api/knowledge)

echo "=== CRON JOBS ==="
docker exec aria-engine aria-engine cron list 2>/dev/null | head -20

echo "=== MLX INFERENCE TEST ==="
if [[ -f /tmp/test_mlx.py ]]; then
  python3 /tmp/test_mlx.py 2>&1
else
  echo "  /tmp/test_mlx.py not found (skipped)"
fi

echo "=== TRAEFIK ROUTING ==="
for path in / /api/health /operations /litellm-proxy; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost${path}" || true)
  echo "  traefik${path} -> ${code}"
done

echo "=== DONE ==="
