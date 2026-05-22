import requests
import logging
from config.settings import WEBHOOK_URL

logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self):
        self.webhook_url = WEBHOOK_URL

    def send_notification(self, title: str, message: str, level: str = "INFO"):
        if self.webhook_url in (None, "", "your_webhook_url_here"):
            logger.info("Webhook skipped: URL not configured.")
            return

        colors = {
            "INFO": 3447003,      # Blue
            "WARNING": 16776960,  # Yellow
            "ERROR": 16711680     # Red
        }

        color = colors.get(level.upper(), colors["INFO"])

        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color
                }
            ]
        }

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=5)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
