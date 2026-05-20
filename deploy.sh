#!/bin/bash
# Run chmod +x deploy.sh before executing

# Environment Failsafe
if [ ! -f .env ]; then
    echo -e "\033[0;31mError: .env file not found. Please create it based on .env.example\033[0m"
    exit 1
fi

# Code Sync
git pull

# Teardown
podman compose down

# Build
podman compose build

# Cleanup
podman image prune -f

# Launch
podman compose up -d
