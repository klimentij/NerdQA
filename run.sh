#!/bin/bash

# Colors for pretty output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Required environment variables
REQUIRED_VARS=("OPENAI_API_KEY" "COHERE_API_KEY" "EXA_SEARCH_API_KEY")
ENV_FILE="backend/config/.env"
ENV_DIST_FILE="backend/config/.env.dist"

# Function to check and create .env file
check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${YELLOW}⚠️  No .env file found. Creating one...${NC}"
        cp "$ENV_DIST_FILE" "$ENV_FILE"
    fi

    missing_vars=()
    for var in "${REQUIRED_VARS[@]}"; do
        # Check if variable is missing or empty in .env file
        if ! grep -q "^${var}=\"[^\"]*\"$" "$ENV_FILE" || grep -q "^${var}=\"\"$" "$ENV_FILE"; then
            missing_vars+=("$var")
        fi
    done

    if [ ${#missing_vars[@]} -ne 0 ]; then
        echo -e "${YELLOW}⚠️  Some required environment variables are not set:${NC}"
        for var in "${missing_vars[@]}"; do
            echo -e "${YELLOW}Please enter value for $var:${NC}"
            read -r value
            # Export the variable for current session
            export "$var=$value"
            # Update or add the variable in .env file
            if grep -q "^${var}=" "$ENV_FILE"; then
                # If variable exists, update it
                sed -i.bak "s|^${var}=.*|${var}=\"${value}\"|" "$ENV_FILE" && rm "$ENV_FILE.bak"
            else
                # If variable doesn't exist, add it
                echo "${var}=\"${value}\"" >> "$ENV_FILE"
            fi
        done
        echo -e "${GREEN}✅ Environment variables have been updated.${NC}"
    fi
}

echo -e "${GREEN}🚀 Building and running NerdQA...${NC}"

# Check environment variables before proceeding
check_env_file

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