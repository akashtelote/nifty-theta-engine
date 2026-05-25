import os
from dotenv import load_dotenv

load_dotenv() # Force environment variables to load before evaluating constants

# Timeouts for API connections
CONNECTION_TIMEOUT = float(os.getenv("CONNECTION_TIMEOUT", "10.0"))
READ_TIMEOUT = float(os.getenv("READ_TIMEOUT", "30.0"))

# Webhook configuration
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
