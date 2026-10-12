#!/bin/bash
# Run chmod +x deploy.sh before executing
set -e

# Everything runs inside main() so bash parses this whole body into memory
# before executing any of it. git pull below rewrites this very file on
# disk — without the function wrapper, bash keeps reading the now-stale
# file for the remaining lines, which can silently execute pre-pull code.
main() {
    # Environment Failsafe
    if [ ! -f .env ]; then
        echo -e "\033[0;31mError: .env file not found. Please create it based on .env.example\033[0m"
        exit 1
    fi

    # Code Sync
    git pull

    # Build first: a failed build must leave the running containers untouched.
    # (up -d below recreates only what changed, so no explicit teardown.)
    docker compose build

    # Cleanup
    docker image prune -f

    # Launch
    docker compose up -d
}

main "$@"
