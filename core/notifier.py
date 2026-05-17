import requests
import logging
from config.settings import WEBHOOK_URL

logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self):
        self.webhook_url = WEBHOOK_URL

    def send_message(self, message: str):
        if not self.webhook_url:
            return

        payload = {"content": message}
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=5)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
