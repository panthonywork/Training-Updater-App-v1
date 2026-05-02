#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  echo "First run — setting up environment (this takes ~30 seconds)..."
  python3 -m pip install uv -q
  python3 -m uv venv .venv
  python3 -m uv pip install -r requirements.txt --python .venv/bin/python3
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  Add your ANTHROPIC_API_KEY to the .env file before using AI features."
fi

# Kill any existing session on 8501
lsof -ti:8501 | xargs kill -9 2>/dev/null || true
sleep 1

# Start Streamlit in the background
echo "Starting TD Collateral Modernizer..."
.venv/bin/streamlit run app.py --server.port 8501 --server.headless true &

# Wait until the server responds before opening the browser
echo "Waiting for server..."
until curl -s http://localhost:8501 > /dev/null; do
  sleep 1
done

echo "Ready — opening browser..."
open "http://localhost:8501"

# Keep the terminal window open so the app stays alive
wait
