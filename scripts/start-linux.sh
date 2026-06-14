#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Virtual environment not found. Run scripts/install-linux.sh first." >&2
  exit 1
fi

cd "$ROOT"
exec "$PY" -m wavepilot "$@"
