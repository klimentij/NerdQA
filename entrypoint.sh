#!/bin/bash

# Start Redis
redis-server /etc/redis/redis.conf --daemonize yes

# Start LiteLLM proxy
python backend/src/llm/run_litellm.py &

# Start server.py
uvicorn src.qloop.server:app --reload --host 0.0.0.0 --port 8000 &

# Serve frontend
cd frontend && python3 -m http.server 8080

# Keep the container running
tail -f /dev/null