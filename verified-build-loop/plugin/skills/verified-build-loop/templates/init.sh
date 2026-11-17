#!/usr/bin/env bash
# Startup routine for each session: install dependencies, then run a quick smoke check.
# Setup replaces these lines with the project's real commands.
set -euo pipefail
cd "$(dirname "$0")"
echo "== install =="
# example: python3 -m pip install -r requirements.txt
echo "== smoke check =="
# example: python3 -m pytest -x -q tests/test_smoke.py
echo "init.sh finished"
