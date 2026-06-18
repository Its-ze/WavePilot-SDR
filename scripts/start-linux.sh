#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/wavepilot-sdr}"
INSTALLED_PY="$INSTALL_DIR/.venv/bin/python"

if [ -x "$PY" ]; then
  cd "$ROOT"
  exec "$PY" -m wavepilot "$@"
fi

if [ -x "$INSTALLED_PY" ]; then
  cd "$INSTALL_DIR"
  exec "$INSTALLED_PY" -m wavepilot "$@"
fi

if command -v wavepilot-sdr >/dev/null 2>&1; then
  exec wavepilot-sdr "$@"
fi

echo "Virtual environment not found. Run scripts/install-linux.sh first." >&2
exit 1
