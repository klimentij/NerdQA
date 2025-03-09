#!/bin/bash

# Colors for pretty output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Building and running NerdQA...${NC}"

# Stop and remove existing container if it exists
if [ "$(docker ps -q -f name=nerdqa)" ]; then
    echo "Stopping existing NerdQA container..."
    docker stop nerdqa
fi
if [ "$(docker ps -aq -f name=nerdqa)" ]; then
    echo "Removing existing NerdQA container..."
    docker rm nerdqa
fi

# Build the Docker image
echo -e "\n${GREEN}📦 Building Docker image...${NC}"
docker build -t nerdqa .

# Check if build was successful
if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}🎉 Build successful! Starting container...${NC}"
    
    # Run the container
    docker run -d \
        --name nerdqa \
        -p 8000:8000 \
        -p 8080:8080 \
        -p 6379:6379 \
        -p 4000:4000 \
        nerdqa

    echo -e "\n${GREEN}✨ NerdQA is running!${NC}"
    echo -e "Frontend: http://localhost:8080"
    echo -e "Backend API: http://localhost:8000"
    echo -e "LiteLLM Proxy: http://localhost:4000"
    echo -e "\nTo view logs: docker logs nerdqa"
    echo -e "To stop: docker stop nerdqa"
else
    echo -e "\n${RED}❌ Build failed${NC}"
    exit 1
fi