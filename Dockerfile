# Use Python 3.11-slim as the base image
FROM python:3.11-slim

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    redis-server \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to PATH
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy the entire project into the container
COPY . /app

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Install Python dependencies
RUN python -m venv /venv && \
    . /venv/bin/activate && \
    uv pip install --prerelease=allow -r backend/config/requirements.txt

# Configure Redis
COPY backend/config/redis.conf /etc/redis/redis.conf
RUN mkdir -p /data/redis && \
    chown -R redis:redis /data/redis

# Set Python path
ENV PYTHONPATH=/app

# Expose ports
EXPOSE 6379 8000 4000 8080

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Set the default command to an empty array
CMD []
