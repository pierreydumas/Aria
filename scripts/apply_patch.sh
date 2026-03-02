#!/usr/bin/env bash
set -euo pipefail

PATCH_DIR="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/stacks/brain/docker-compose.yml"
STACK_ENV_FILE="$ROOT_DIR/stacks/brain/.env"
BACKUP_DIR="$ROOT_DIR/aria_memories/exports/patch_backup_$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$ROOT_DIR/aria_memories/logs/apply_patch_$(date +%Y%m%d_%H%M%S).log"

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

if [[ -z "$PATCH_DIR" ]]; then
  echo "Usage: $0 <patch-directory>"
  exit 1
fi

if [[ ! -d "$PATCH_DIR" ]]; then
  echo "Patch directory not found: $PATCH_DIR"
  exit 1
fi

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG_FILE")"

echo "[apply_patch] root=$ROOT_DIR patch=$PATCH_DIR" | tee -a "$LOG_FILE"

rollback() {
  echo "[apply_patch] rollback started" | tee -a "$LOG_FILE"
  rsync -a "$BACKUP_DIR/" "$ROOT_DIR/" | tee -a "$LOG_FILE"
  docker compose -f "$COMPOSE_FILE" restart aria-api aria-web aria-brain | tee -a "$LOG_FILE"
  echo "[apply_patch] rollback complete" | tee -a "$LOG_FILE"
}

trap 'echo "[apply_patch] failed" | tee -a "$LOG_FILE"; rollback; exit 1' ERR

while IFS= read -r relpath; do
  [[ -z "$relpath" ]] && continue
  src="$PATCH_DIR/$relpath"
  dst="$ROOT_DIR/$relpath"
  if [[ ! -f "$src" ]]; then
    echo "Missing patch file: $src" | tee -a "$LOG_FILE"
    exit 1
  fi
  mkdir -p "$BACKUP_DIR/$(dirname "$relpath")" "$(dirname "$dst")"
  if [[ -f "$dst" ]]; then
    cp "$dst" "$BACKUP_DIR/$relpath"
  fi
  cp "$src" "$dst"
  echo "[apply_patch] replaced $relpath" | tee -a "$LOG_FILE"
done < <(cd "$PATCH_DIR" && find . -type f ! -name '*.md' ! -name '*.log' | sed 's|^./||')

docker compose -f "$COMPOSE_FILE" restart aria-api aria-web aria-brain | tee -a "$LOG_FILE"

api_code="$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${API_PORT}/health" || true)"
web_code="$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${WEB_PORT}/" || true)"
if [[ "$api_code" != "200" || "$web_code" != "200" ]]; then
  echo "[apply_patch] verification failed api=$api_code web=$web_code" | tee -a "$LOG_FILE"
  rollback
  exit 1
fi

echo "[apply_patch] success" | tee -a "$LOG_FILE"
