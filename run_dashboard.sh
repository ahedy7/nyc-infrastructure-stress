#!/usr/bin/env bash
# Run from repo root: ./run_dashboard.sh
cd "$(dirname "$0")/nyc-infrastructure-stress" || exit 1
PY="${PWD}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python
exec "$PY" dashboard/app.py
