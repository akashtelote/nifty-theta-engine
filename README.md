# upstox-wheel-options

## Deployment

The bot can be deployed headlessly using Podman and Podman Compose. The default setup runs the bot in **paper-trading mode**.

### Environment Setup

*Note: If your local Podman installation throws a 'compose provider failed' error, you may need to install the companion package via `pip install podman-compose` or ensure a native compose binary is configured in your system PATH.*

Before deploying the bot, you must create a `.env` file at the root level of the repository. This file must contain the following variables:
- `UPSTOX_USER_ID`
- `UPSTOX_PASSWORD`
- `UPSTOX_PIN_CODE`
- `UPSTOX_TOTP_SECRET`
- `UPSTOX_API_KEY`
- `UPSTOX_API_SECRET`
- `UPSTOX_REDIRECT_URI`
- `WEBHOOK_URL`

Because `core/auth.py` utilizes the `UpstoxTOTP` package, upon running the deployment script, the bot will use these credentials to headlessly authenticate and generate the initial `token.json` file inside the persistent volume. Zero manual browser intervention is required.

### Deployment Script

To automate the update and deployment lifecycle, we use the `deploy.sh` script.

1. First, make sure the script is executable:
   ```bash
   chmod +x deploy.sh
   ```
2. Run the deployment script to pull the latest code, rebuild the Podman image, and restart the container:
   ```bash
   ./deploy.sh
   ```
3. The bot will automatically run in the background. State and tokens will be persisted in the `./data` directory on your host machine.

### Paper Trading Incubation

After deploying the bot in the default paper-trading mode, it is highly recommended to monitor its behavior before enabling live trading.

Monitor the configured `WEBHOOK_URL` at **15:15 IST** (the time when the bot evaluates and potentially rolls or closes positions). Use these daily notifications to verify the bot's state machine is operating correctly, correctly identifying expirations, making appropriate roll decisions, and managing state transitions without errors.

### Live Trading

**Important:** You should only enable live trading after successfully verifying your configuration and strategy via paper trading.

Once you have verified the bot's operation during the paper trading incubation period, you can switch to live trading mode by adding the `--live` flag to the podman compose execution command.

Override the default command in your `docker-compose.yml` file by adding the `command` directive under the `upstox-wheel-bot` service:

```yaml
version: "3.8"

services:
  upstox-wheel-bot:
    build: .
    container_name: upstox-wheel-bot
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - TZ=Asia/Kolkata
    volumes:
      - ./data:/app/data
    # Add this line to enable live trading
    command: ["uv", "run", "python", "main.py", "start", "--live"]
```

After modifying the file, restart the container using the deployment script:
```bash
./deploy.sh
```

### Troubleshooting

**Visual Verification Note**
In modern Podman versions, the bot will appear as a standalone Container named `upstox-wheel-bot`, not inside a combined Pod.

**Network Conflict Note**
If you switch from legacy compose to modern Podman updates, you might encounter a network label error (`incorrect label com.docker.compose.network`). To resolve this, run `podman network rm upstox-wheel-options_default` before executing `podman compose up -d`.
