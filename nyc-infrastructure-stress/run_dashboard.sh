#!/bin/bash
# Run the dashboard - kills any existing process on port 8050 first
cd "$(dirname "$0")"
PY="${PWD}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python
echo "Stopping any existing dashboard on port 8050..."
lsof -ti:8050 | xargs kill -9 2>/dev/null || true
sleep 1
echo "Starting dashboard..."
exec "$PY" dashboard/app.py
