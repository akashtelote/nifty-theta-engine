# =========================================================
# Upstox Wheel Bot - Automated Deployment Pipeline
# =========================================================

$SERVER_USER = "your_ssh_username"
$SERVER_IP = "192.168.x.x"  # Or your Tailscale IP
$TARGET_DIR = "~/trading-bot"

Write-Host "Initiating deployment to $SERVER_USER@$SERVER_IP..." -ForegroundColor Cyan

# Step 1: Create target directory on the server if it doesn't exist
ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${TARGET_DIR}/data"

# Step 2: Sync Core Application Files (Excluding /data and backtester)
Write-Host "Transferring application files..." -ForegroundColor Yellow
scp -r ./core ./strategies ./main.py ./dashboard.py ./Dockerfile ./podman-compose.yml ./pyproject.toml ./uv.lock ./.env ${SERVER_USER}@${SERVER_IP}:${TARGET_DIR}

# Step 3: Remote Execution - Rebuild and Restart Containers
Write-Host "Rebuilding Podman containers on the remote server..." -ForegroundColor Yellow
ssh ${SERVER_USER}@${SERVER_IP} "cd ${TARGET_DIR} && podman compose down && podman compose build --no-cache && podman compose up -d"

Write-Host "==================================================" -ForegroundColor Green
Write-Host "DEPLOYMENT SUCCESSFUL! The Engine is Online." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green