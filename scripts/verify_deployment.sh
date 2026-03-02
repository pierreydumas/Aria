#!/usr/bin/env bash
set -euo pipefail

QUICK=0
if [[ "${1:-}" == "--quick" ]]; then
  QUICK=1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/stacks/brain/docker-compose.yml"
STACK_ENV_FILE="$ROOT_DIR/stacks/brain/.env"
LOG_FILE="$ROOT_DIR/aria_memories/logs/deploy_verify_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"

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

failures=0

check_http() {
  local name="$1"
  local url="$2"
  local expected="$3"
  local code
  code="$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)"
  echo "HTTP $name $url => $code" | tee -a "$LOG_FILE"
  if [[ "$code" != "$expected" ]]; then
    failures=$((failures + 1))
  fi
}

echo "== container status ==" | tee -a "$LOG_FILE"
docker compose -f "$COMPOSE_FILE" ps | tee -a "$LOG_FILE"

required=(aria-db aria-api aria-web aria-brain litellm traefik)
for name in "${required[@]}"; do
  if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
    echo "missing container: $name" | tee -a "$LOG_FILE"
    failures=$((failures + 1))
  fi
done

check_http "api-health" "http://localhost:${API_PORT}/health" "200"
check_http "web-root" "http://localhost:${WEB_PORT}/" "200"
check_http "social" "http://localhost:${API_PORT}/api/social" "200"
check_http "security" "http://localhost:${API_PORT}/api/security-events" "200"
check_http "rate-limits" "http://localhost:${API_PORT}/api/rate-limits" "200"

if (( QUICK == 0 )); then
  check_http "goals" "http://localhost:${WEB_PORT}/goals" "200"
  check_http "memories" "http://localhost:${WEB_PORT}/memories" "200"
  check_http "knowledge" "http://localhost:${WEB_PORT}/knowledge" "200"
  check_http "sprint-board" "http://localhost:${WEB_PORT}/sprint-board" "200"
fi

if (( failures > 0 )); then
  echo "verification failed: $failures checks" | tee -a "$LOG_FILE"
  exit 1
fi

echo "verification passed" | tee -a "$LOG_FILE"
