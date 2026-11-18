#!/usr/bin/env sh
# FrontierTwin launcher for Ubuntu / DGX OS / macOS
# Developer: Subramoniam AB (SAB)
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && { echo "Python 3.8+ is required (sudo apt install python3 / brew install python)"; exit 1; }
exec "$PY" ft.py serve "$@"
