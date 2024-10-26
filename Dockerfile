# Use a lightweight Ubuntu base image
FROM ubuntu:22.04

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3-pip \
    python3-venv \
    git \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install uv
RUN pip3 install --no-cache-dir --upgrade pip==24.2 \
    && pip3 install --no-cache-dir uv==0.1.24

# Clone the NerdQA repository
RUN git clone https://github.com/klimentij/NerdQA.git .

# Create venv and install dependencies
RUN python3.11 -m venv /venv
ENV PATH="/venv/bin:$PATH"
RUN uv venv --python=3.11 && \
    uv pip install -r backend/config/requirements.txt

# Configure Redis
COPY backend/config/redis.conf /etc/redis/redis.conf
RUN mkdir -p /data/redis && \
    chown -R redis:redis /data/redis

# Create entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose ports
EXPOSE 6379 8000 8080

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Set the default command to an empty array
CMD []
