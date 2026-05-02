#!/bin/bash
# TD Collateral Modernizer — launch script
# Usage: bash launch.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Create venv if missing
if [ ! -d ".venv" ]; then
  echo "Setting up virtual environment..."
  python3 -m pip install uv -q
  python3 -m uv venv .venv
  python3 -m uv pip install -r requirements.txt --python .venv/bin/python3
fi

# Check .env exists
if [ ! -f ".env" ]; then
  echo "⚠️  No .env file found. Copying from .env.example..."
  cp .env.example .env
  echo "   → Add your ANTHROPIC_API_KEY to .env before using AI features."
fi

# Kill any existing Streamlit on 8501
lsof -ti:8501 | xargs kill -9 2>/dev/null || true

echo "Starting TD Collateral Modernizer at http://localhost:8501 ..."
.venv/bin/streamlit run app.py --server.port 8501 --server.headless false
