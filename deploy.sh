#!/bin/bash
# Run chmod +x deploy.sh before executing

RED='\033[0;31m'
NC='\033[0m' # No Color

# Environment Failsafe
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found. Please create it based on .env.example${NC}"
    exit 1
fi

# Code Sync
echo "Fetching latest code..."
git pull

# Teardown
echo "Tearing down existing containers..."
podman compose down

# Build
echo "Building new image..."
podman compose build

# Cleanup
echo "Cleaning up dangling images..."
podman image prune -f

# Launch
echo "Launching bot in the background..."
podman compose up -d

echo "Deployment complete."
