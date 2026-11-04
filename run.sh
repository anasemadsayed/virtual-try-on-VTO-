#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Created .env - put your PERFECT_API_KEY in it, then run ./run.sh again."; exit 1; }
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
