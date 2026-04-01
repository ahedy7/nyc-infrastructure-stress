#!/usr/bin/env bash
# Run from repo root: ./run_dashboard.sh
cd "$(dirname "$0")/nyc-infrastructure-stress" || exit 1
exec python dashboard/app.py
