podman compose down
podman compose build --no-cache
podman image prune -f
podman compose up -d