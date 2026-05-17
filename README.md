# upstox-wheel-options

## Deployment

The bot can be deployed headlessly using Docker and Docker Compose. The default setup runs the bot in **paper-trading mode**.

### Starting the Bot

1. Ensure your `.env` file is properly configured with your Upstox API credentials and settings.
2. Build and start the bot using Docker Compose:
   ```bash
   docker-compose up -d
   ```
3. The bot will automatically run in the background. State and tokens will be persisted in the `./data` directory on your host machine.

### Live Trading

**Important:** You should only enable live trading after successfully verifying your configuration and strategy via paper trading.

To switch to live trading mode, override the default command in your `docker-compose.yml` file by adding the `command` directive under the `upstox-wheel-bot` service:

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

After modifying the file, restart the container:
```bash
docker-compose up -d
```
