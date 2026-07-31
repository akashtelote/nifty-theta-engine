# =========================================================
# Nifty Theta Engine - Oracle Cloud Deployment Pipeline
# =========================================================

$ErrorActionPreference = "Stop"

$SERVER_USER = "ubuntu"
$SERVER_IP = "140.245.220.235"
$SSH_KEY = "C:\Users\akash\.ssh\ssh-key-2026-07-02.key"
$TARGET_DIR = "~/nifty-theta-engine"
$SSH_OPTS = @("-i", $SSH_KEY, "-o", "StrictHostKeyChecking=accept-new")

function Invoke-Remote {
    param([string]$Command)
    ssh @SSH_OPTS "${SERVER_USER}@${SERVER_IP}" $Command
}

if (-not (Test-Path ".env")) {
    Write-Host "Error: .env file not found. Create it from .env.example first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $SSH_KEY)) {
    Write-Host "Error: SSH key not found at $SSH_KEY" -ForegroundColor Red
    exit 1
}

Write-Host "Initiating deployment to ${SERVER_USER}@${SERVER_IP}..." -ForegroundColor Cyan

# Step 1: Create remote directories
Write-Host "Creating remote directories..." -ForegroundColor Yellow
Invoke-Remote "mkdir -p ${TARGET_DIR}/data ${TARGET_DIR}/config ${TARGET_DIR}/core ${TARGET_DIR}/strategies ${TARGET_DIR}/execution"

# Step 2: Sync application files
Write-Host "Transferring application files..." -ForegroundColor Yellow
$remote = "${SERVER_USER}@${SERVER_IP}:${TARGET_DIR}"

scp @SSH_OPTS `
    ./main.py `
    ./dashboard.py `
    ./backtest.py `
    ./Dockerfile `
    ./docker-compose.yml `
    ./pyproject.toml `
    ./uv.lock `
    ./init_nifty_schema.sql `
    ./.env `
    "${remote}/"

scp @SSH_OPTS -r `
    ./core `
    ./strategies `
    ./config `
    "${remote}/"

if (Test-Path "./execution") {
    scp @SSH_OPTS -r ./execution "${remote}/"
}

# Step 3: Enforce paper mode + Redis/Postgres wiring on the server .env
Write-Host "Enforcing paper-trade env on server..." -ForegroundColor Yellow
$patchScript = @'
from pathlib import Path
path = Path(".env")
text = path.read_text(encoding="utf-8") if path.exists() else ""
lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
kv = {}
order = []
for ln in lines:
    if "=" not in ln:
        continue
    k, v = ln.split("=", 1)
    if k not in kv:
        order.append(k)
    kv[k] = v

overrides = {
    "PAPER_TRADE": "True",
    "MOCK_MARKET": "False",
    "REDIS_URL": "redis://host.docker.internal:6379/0",
}
for k, v in overrides.items():
    if k not in kv:
        order.append(k)
    kv[k] = v

user = kv.get("POSTGRES_USER", "wheelbot")
password = kv.get("POSTGRES_PASSWORD", "securepassword")
db = kv.get("POSTGRES_DB", "wheeldb")
kv["DATABASE_URL"] = f"postgresql://{user}:{password}@db:5432/{db}"
if "DATABASE_URL" not in order:
    order.append("DATABASE_URL")
for required in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
    if required not in kv:
        raise SystemExit(f"Missing required {required} in .env")

path.write_text("\n".join(f"{k}={kv[k]}" for k in order) + "\n", encoding="utf-8")
print("env patched: PAPER_TRADE=True MOCK_MARKET=False REDIS_URL=host.docker.internal DATABASE_URL=@db")
'@
$patchLocal = Join-Path $env:TEMP "nifty_patch_env.py"
[System.IO.File]::WriteAllText($patchLocal, $patchScript)
scp @SSH_OPTS $patchLocal "${remote}/patch_env.py"
Invoke-Remote "cd ${TARGET_DIR} && python3 patch_env.py && rm -f patch_env.py"
Remove-Item $patchLocal -ErrorAction SilentlyContinue

# Step 4: Rebuild and restart Docker Compose stack
Write-Host "Rebuilding Docker containers on the remote server..." -ForegroundColor Yellow
Invoke-Remote "cd ${TARGET_DIR} && docker compose down && docker compose up -d --build"

Write-Host "==================================================" -ForegroundColor Green
Write-Host "DEPLOYMENT SUCCESSFUL! The Engine is Online." -ForegroundColor Green
Write-Host "Dashboard (Tailscale): http://100.65.198.84:8502" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
