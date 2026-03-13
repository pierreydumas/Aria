#!/bin/sh
# Aria API entrypoint — structured JSON logging configuration (S-24)
set -e

echo "=== Aria API Entrypoint ==="

# Configure structured JSON logging via environment
export LOG_FORMAT="${LOG_FORMAT:-json}"
export LOG_LEVEL="${LOG_LEVEL:-info}"

# Apply JSON access log format for uvicorn
if [ "$LOG_FORMAT" = "json" ]; then
    export UVICORN_ACCESS_LOG="--no-access-log"
    echo "Structured JSON logging enabled (level=$LOG_LEVEL)"
else
    export UVICORN_ACCESS_LOG=""
    echo "Plain text logging enabled (level=$LOG_LEVEL)"
fi

echo "Starting Aria API..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${API_INTERNAL_PORT:-8000}" \
    --workers "${API_WORKERS:-2}" \
    --timeout-keep-alive 300 \
    --log-level "$LOG_LEVEL" \
    $UVICORN_ACCESS_LOG \
    "$@"
