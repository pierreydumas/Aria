#!/usr/bin/env bash
set -euo pipefail

SEED_FILE="stacks/brain/working_memory_seed.default.json"
API_BASE_URL="${ARIA_API_BASE_URL:-http://localhost:8000/api}"
API_KEY="${ARIA_API_KEY:-}"
CONTINUE_ON_ERROR=true

usage() {
  cat <<EOF
Usage: $(basename "$0") [--seed-file <path>] [--api-base-url <url>] [--strict]

Imports working-memory defaults via API.

Options:
  --seed-file <path>     Seed JSON file (default: stacks/brain/working_memory_seed.default.json)
  --api-base-url <url>   API base URL (default: http://localhost:8000/api)
  --strict               Stop on first failed item (default: continue)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed-file)
      SEED_FILE="$2"
      shift 2
      ;;
    --api-base-url)
      API_BASE_URL="$2"
      shift 2
      ;;
    --strict)
      CONTINUE_ON_ERROR=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "${SEED_FILE_SET:-}" && -f "$1" ]]; then
        SEED_FILE="$1"
        SEED_FILE_SET=1
        shift
      else
        echo "Unknown argument: $1" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

if [[ ! -f "$SEED_FILE" ]]; then
  echo "Seed file not found: $SEED_FILE" >&2
  exit 1
fi

AUTH_HEADER=()
if [[ -n "$API_KEY" ]]; then
  AUTH_HEADER=(-H "X-API-Key: $API_KEY")
fi

count=0
failed=0
while IFS= read -r item; do
  key=$(jq -r '.key' <<<"$item")
  category=$(jq -r '.category // "general"' <<<"$item")
  value=$(jq -c '.value' <<<"$item")
  importance=$(jq -r '.importance // 0.5' <<<"$item")
  source=$(jq -r '.source // "seed.default"' <<<"$item")

  payload=$(jq -n \
    --arg key "$key" \
    --arg category "$category" \
    --argjson value "$value" \
    --arg source "$source" \
    --argjson importance "$importance" \
    '{key:$key, category:$category, value:$value, importance:$importance, source:$source}')

  response_file=$(mktemp)
  status_code=$(curl -sS -o "$response_file" -w '%{http_code}' -X POST "$API_BASE_URL/working-memory" \
    -H "Content-Type: application/json" \
    "${AUTH_HEADER[@]}" \
    -d "$payload" || true)

  if [[ "$status_code" =~ ^2 ]]; then
    count=$((count + 1))
    echo "Seeded: $key"
  else
    failed=$((failed + 1))
    echo "Failed: $key (HTTP $status_code)" >&2
    tail -c 240 "$response_file" >&2 || true
    echo >&2
    rm -f "$response_file"
    if [[ "$CONTINUE_ON_ERROR" != "true" ]]; then
      exit 1
    fi
    continue
  fi

  rm -f "$response_file"
done < <(jq -c '.items[]' "$SEED_FILE")

echo "Done. Seeded $count working-memory item(s); failed $failed item(s) from $SEED_FILE"

if [[ "$failed" -gt 0 ]]; then
  exit 1
fi
