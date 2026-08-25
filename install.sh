#!/usr/bin/env bash
# AnnexAI - one-command installer for macOS / Linux.
#
# Usage:
#   ./install.sh                 # install everything (skips work that's done)
#   ./install.sh --force         # force a clean reinstall
#   ./install.sh --auto-tools    # also try to install brew/apt prereqs
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3.10+ is required but was not found on PATH."
  case "$(uname -s)" in
    Darwin)
      echo "Install it with:  brew install python"
      ;;
    Linux)
      echo "Install it with:  sudo apt install -y python3 python3-venv python3-pip"
      ;;
    *)
      echo "Download from:    https://www.python.org/downloads"
      ;;
  esac
  exit 1
fi

exec "$PY" install.py "$@"
