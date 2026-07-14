#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
  echo "[ERR] .venv not found. Please run: python3 -m venv .venv"
  exit 1
fi

source .venv/bin/activate

TOP_N="${1:-20}"
PYTHONPATH=. python 03_Quant_Data/run_pipeline_stage3.py --with-themes --top-n "$TOP_N"

echo "[OK] stage3 pipeline finished."
