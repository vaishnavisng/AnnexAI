#!/usr/bin/env bash
# AnnexAI - one-command launcher for macOS / Linux.
#
# Usage:
#   ./start.sh                  # backend + frontend, opens browser
#   ./start.sh --backend-only
#   ./start.sh --frontend-only
#   ./start.sh --no-browser
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3.10+ is required but was not found on PATH."
  echo "Run ./install.sh first, or install Python from https://www.python.org/downloads"
  exit 1
fi

exec "$PY" start.py "$@"
