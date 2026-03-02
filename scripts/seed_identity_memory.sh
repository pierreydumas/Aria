#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SEED_DIR="$REPO_ROOT/stacks/brain/identity_seed.default"
TARGET_DIR="$REPO_ROOT/aria_memories/memory"
FORCE=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [--force] [--seed-dir <path>] [--target-dir <path>]

Seeds clone-safe identity files into aria_memories/memory.
Default behavior only creates missing files.

Options:
  --force              Overwrite existing target files
  --seed-dir <path>    Alternate seed directory
  --target-dir <path>  Alternate target directory
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=true
      shift
      ;;
    --seed-dir)
      SEED_DIR="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

FILES=(
  "identity_aria_v1.md"
  "identity_najia_v1.md"
  "identity_index.md"
)

if [[ ! -d "$SEED_DIR" ]]; then
  echo "Seed directory not found: $SEED_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"

seeded=0
skipped=0

for file_name in "${FILES[@]}"; do
  src="$SEED_DIR/$file_name"
  dst="$TARGET_DIR/$file_name"

  if [[ ! -f "$src" ]]; then
    echo "Missing seed file: $src" >&2
    exit 1
  fi

  if [[ -f "$dst" && "$FORCE" != "true" ]]; then
    skipped=$((skipped + 1))
    echo "Skipped existing: $dst"
    continue
  fi

  cp "$src" "$dst"
  seeded=$((seeded + 1))
  echo "Seeded: $dst"
done

echo "Done. Seeded $seeded file(s); skipped $skipped existing file(s)."
