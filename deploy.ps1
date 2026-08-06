# =========================================================
# Nifty Theta Engine - Oracle Cloud Deployment Pipeline
# Prefer: git pull on the server (repo is a clone via GitHub SSH).
# Fallback: scp sync if remote is not a git checkout.
# =========================================================

$ErrorActionPreference = "Stop"

$SERVER_USER = "ubuntu"
$SERVER_IP = "140.245.220.235"
$SSH_KEY = "C:\Users\akash\.ssh\ssh-key-2026-07-02.key"
$TARGET_DIR = "~/nifty-theta-engine"
$SSH_OPTS = @("-i", $SSH_KEY, "-o", "StrictHostKeyChecking=accept-new")

# $ErrorActionPreference does not cover native exes (ssh/scp) on PS 5.1, and is
# version-dependent on PS 7 — check $LASTEXITCODE explicitly or a failed deploy
# still falls through to the green "DEPLOYMENT SUCCESSFUL" banner.
function Assert-LastExit {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED ($LASTEXITCODE): $What" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Invoke-Remote {
    param([string]$Command)
    ssh @SSH_OPTS "${SERVER_USER}@${SERVER_IP}" $Command
    Assert-LastExit "remote: $Command"
}

if (-not (Test-Path $SSH_KEY)) {
    Write-Host "Error: SSH key not found at $SSH_KEY" -ForegroundColor Red
    exit 1
}

Write-Host "Initiating deployment to ${SERVER_USER}@${SERVER_IP}..." -ForegroundColor Cyan

$remote = "${SERVER_USER}@${SERVER_IP}:${TARGET_DIR}"
$isGit = Invoke-Remote "test -d ${TARGET_DIR}/.git && echo YES || echo NO"
$isGit = ($isGit | Out-String).Trim()

if ($isGit -eq "YES") {
    Write-Host "Remote is a git repo — pulling origin/main..." -ForegroundColor Yellow
    Invoke-Remote "cd ${TARGET_DIR} && git fetch origin && git reset --hard origin/main && git log -1 --oneline"
} else {
    Write-Host "Remote is not a git repo — falling back to scp sync..." -ForegroundColor Yellow

    # Only this path uploads .env; the git path uses whatever already lives on the server.
    if (-not (Test-Path ".env")) {
        Write-Host "Error: scp fallback needs a local .env. Create it from .env.example first." -ForegroundColor Red
        exit 1
    }

    Invoke-Remote "mkdir -p ${TARGET_DIR}/data ${TARGET_DIR}/config ${TARGET_DIR}/core ${TARGET_DIR}/strategies ${TARGET_DIR}/execution"

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
    Assert-LastExit "scp root files"

    scp @SSH_OPTS -r `
        ./core `
        ./strategies `
        ./config `
        "${remote}/"
    Assert-LastExit "scp package dirs"

    if (Test-Path "./execution") {
        scp @SSH_OPTS -r ./execution "${remote}/"
        Assert-LastExit "scp execution"
    }

    # ponytail: scp never deletes, so files removed from the repo linger on the
    # server. Fine while this is a rarely-hit fallback; switch to rsync --delete
    # if it ever becomes the normal path.
}

# Enforce paper mode + Redis/Postgres wiring on the server .env
Write-Host "Enforcing paper-trade env on server..." -ForegroundColor Yellow
$patchScript = @'
"""Force the container-facing keys in the server .env, preserving everything else.

Rewrites only the lines it owns: comments, blank lines, ordering and unrelated
keys survive verbatim, so the file stays readable across repeated deploys.
"""
from pathlib import Path

path = Path(".env")
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def key_of(line):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


kv = {}
for line in lines:
    k = key_of(line)
    if k:
        kv[k] = line.split("=", 1)[1]

missing = [r for r in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB") if r not in kv]
if missing:
    raise SystemExit(f"Missing required key(s) in .env: {', '.join(missing)}")

overrides = {
    "PAPER_TRADE": "True",
    "MOCK_MARKET": "False",
    "REDIS_URL": "redis://host.docker.internal:6379/0",
    "DATABASE_URL": (
        f"postgresql://{kv['POSTGRES_USER']}:{kv['POSTGRES_PASSWORD']}"
        f"@db:5432/{kv['POSTGRES_DB']}"
    ),
}

out, seen = [], set()
for line in lines:
    k = key_of(line)
    if k in overrides:
        if k in seen:
            continue  # collapse duplicate definitions of an owned key
        out.append(f"{k}={overrides[k]}")
        seen.add(k)
    else:
        out.append(line)
out.extend(f"{k}={v}" for k, v in overrides.items() if k not in seen)

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("env patched (comments preserved): " + " ".join(sorted(overrides)))
'@
$patchLocal = Join-Path $env:TEMP "nifty_patch_env.py"
[System.IO.File]::WriteAllText($patchLocal, $patchScript)
scp @SSH_OPTS $patchLocal "${remote}/patch_env.py"
Assert-LastExit "scp patch_env.py"
Invoke-Remote "cd ${TARGET_DIR} && python3 patch_env.py && rm -f patch_env.py"
Remove-Item $patchLocal -ErrorAction SilentlyContinue

Write-Host "Rebuilding Docker containers on the remote server..." -ForegroundColor Yellow
Invoke-Remote "cd ${TARGET_DIR} && docker compose up -d --build"

Write-Host "==================================================" -ForegroundColor Green
Write-Host "DEPLOYMENT SUCCESSFUL! The Engine is Online." -ForegroundColor Green
Write-Host "Dashboard (Tailscale): http://100.65.198.84:8502" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
