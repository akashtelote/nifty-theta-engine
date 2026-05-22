PART 1: CODEBASE WIKI
Internal Architecture & Core Modules
main.py
The primary entry point of the trading bot, utilizing argparse to provide a unified Command Line Interface (CLI). It structures execution into distinct subcommands:

auth: Generates or refreshes the Upstox API token.
screen: Runs the Smart Money Filter to find institutional whales.
trade: Allows running a simulated paper trade or a live trade directly.
start: Initializes the daily APScheduler daemon. It includes a --live flag that toggles the execution from the default paper-trading mode to executing real orders on the Upstox exchange.
core/scheduler.py
Manages the automated execution schedule using APScheduler. Configured specifically for the Indian market (Asia/Kolkata timezone), it utilizes a CronTrigger to execute the _run_daily_wheel function precisely at 15:15 IST from Monday to Friday. The scheduler runs in a background thread, kept alive by an infinite sleep loop in the main thread.

core/client.py
Handles all external interactions with the Upstox API.

401 Auto-Healing (_make_authenticated_request): Wraps API calls with self-healing network logic. If a request returns a 401 Unauthorized error, it intercepts the failure, evicts the expired token.json, seamlessly calls the auth module to fetch a fresh token, and retries the request exactly once.
Dynamic Calendar Resolution (get_option_chain): Fetches option contracts and parses their expiry dates to automatically find the most optimal expiration within a mechanical 10 to 42 Days to Expiration (DTE) window. It standardizes the data into a high-performance Polars DataFrame, mapping the instrument_key, strike, expiry, bid, ask, and last_price.
strategies/wheel_strategy.py
The brain of the bot, implementing the Options Wheel Strategy using a deterministic State Machine.

State Flow: The bot progresses through IDLE (looking for a trade) $\rightarrow$ STAGE_1_CSP (selling a Cash-Secured Put) $\rightarrow$ STAGE_2_CC (selling a Covered Call if assigned).
Polars Math: Calculates target options efficiently, seeking Puts 10% Out-of-the-Money (OTM) and Calls mathematically at or above the adjusted cost basis.
State Persistence: Maintains its internal ledger across reboots using a local wheel_state.json file. It leverages filelock to guarantee thread-safe read/write operations during concurrent or automated executions.
core/auth.py
Responsible for the fully headless Upstox token generation. By leveraging the UpstoxTOTP package, it combines the standard credentials (USER_ID, PASSWORD, API_KEY, etc.) with a TOTP_SECRET to automatically fetch an access_token without requiring manual browser-based OAuth logins.

core/notifier.py
The Discord Webhook notification engine. It constructs rich Embed payloads to stream critical updates and errors directly to a Discord channel. It maps log levels to decimal colors: INFO defaults to Blue, WARNING is Yellow, and ERROR triggers Red embeds.

Deployment Specs
deploy.sh: A robust bash script to automate headless Podman deployments. It checks for a .env file, pulls the latest code, tears down existing containers (podman compose down), rebuilds the image, prunes dangling images, and launches the updated container in the background (up -d).
Dockerfile: Uses a slim Python 3.11 base image to minimize footprint. It installs tzdata to enforce the Asia/Kolkata timezone internally and utilizes uv as the lightning-fast package manager. It maximizes build layer caching by syncing pyproject.toml and uv.lock before copying the rest of the application.
PART 2: PRODUCTION README.md
Upstox Wheel Options Trading Bot
An automated, headless Options Trading Bot designed for the Indian Stock Market (NSE) leveraging the Upstox API. This bot programmatically executes the Options Wheel Strategy, cycling through Cash-Secured Puts (CSP) and Covered Calls (CC) using a deterministic state machine and robust quantitative option selection.

⚠️ DISCLAIMER: READ CAREFULLY
THIS SOFTWARE IS FOR EDUCATIONAL PURPOSES ONLY.

Trading financial derivatives, including options, involves significant financial risk and may not be suitable for all investors. You can lose substantial amounts of capital. The authors, contributors, and maintainers of this repository are NOT financial advisors and are NOT responsible for any financial losses or damages incurred from using this software. Always review the code carefully and thoroughly test in paper-trading/mock mode before ever running with live funds. Use at your own risk.

✨ Key Features
Automated State Machine: Deterministically moves between IDLE, STAGE_1_CSP, and STAGE_2_CC states, saving progress locally to ensure recovery across reboots.
Auto-Healing API Network: Inline 401 auto-healing logic seamlessly drops expired tokens, re-authenticates completely headlessly via TOTP, and retries failed API calls.
Polars-Driven Options Math: Lightning-fast quantitative processing to dynamically resolve the optimal 10-42 DTE expiration calendars and calculate strictly 10% OTM target strikes.
Rootless Podman Deployment: Fully containerized architecture using uv for hyper-fast dependency management and APScheduler for precise 15:15 IST execution.
Rich Discord Notifications: Real-time webhook streaming of state changes, executions, and critical errors right to your server.
📋 Prerequisites
Runtime: Linux environment with Podman and podman-compose installed.
Language: Python 3.11 / 3.12
Broker: Upstox API Developer Credentials (API Key, API Secret, User ID, Password, PIN, and TOTP Secret).
Notifications: A Discord Server with Webhook URL capabilities.
🔐 Environment Variables
Create a .env file in the root of the repository matching this template:

# Upstox API Credentials
UPSTOX_USER_ID=your_upstox_id
UPSTOX_PASSWORD=your_password
UPSTOX_PIN_CODE=your_6_digit_pin
UPSTOX_TOTP_SECRET=your_base32_totp_secret
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_REDIRECT_URI=https://127.0.0.1:5000/

# External Integrations
WEBHOOK_URL=your_discord_webhook_url

# Feature Flags
MOCK_MARKET=False
🚀 Installation & Deployment
Clone the repository:
git clone <your-repo-url>
cd upstox-wheel-bot
Setup the Environment: Create and populate the .env file with your credentials as shown above.
Deploy Headlessly (Production): Ensure deploy.sh has execution permissions, then run the build sequence:
chmod +x deploy.sh
./deploy.sh
💻 Usage / Local Testing
For local development or testing, it is highly recommended to utilize uv.

1. Authentication Check: Manually force the bot to login headlessly and generate the token.json.

uv run python main.py auth
2. Start the Bot in Paper-Trading Mode: Boot up the scheduler locally without pushing live trades to Upstox.

uv run python main.py start
3. Start the Bot in LIVE Mode: Append the live flag to execute real, funded exchange orders.

uv run python main.py start --live
🧪 MOCK_MARKET Testing Mode: If you want to test the bot's logic and state machine safely when the Indian F&O market is closed or when you don't want to hit the live API, simply set MOCK_MARKET=True in your .env file. The bot will automatically inject mock market data and dummy Option Chains, allowing you to safely observe the state machine progression without external dependencies.