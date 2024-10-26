#!/bin/bash

# Activate virtual environment
source /venv/bin/activate

# Load environment variables
set -a
source /app/backend/config/.env
set +a

# Create logs directory if it doesn't exist
mkdir -p /app/backend/logs

# Start Redis
redis-server /etc/redis/redis.conf --daemonize yes

# Start LiteLLM proxy
python /app/backend/src/llm/run_litellm.py &

# Start server.py
cd /app && uvicorn backend.src.qloop.server:app --reload --host 0.0.0.0 --port 8000 &

# Serve frontend
cd /app/frontend && python3 -m http.server 8080 &

# Keep the container running
tail -f /dev/null