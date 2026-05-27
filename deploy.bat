:: 1. Gracefully shut down the current trading bot and dashboard
podman compose down

:: 2. Rebuild only what changed (using cache) and start the containers in the background
podman compose up -d --build

:: 3. Clean up any old, untagged image layers left behind by the new build
podman image prune -f