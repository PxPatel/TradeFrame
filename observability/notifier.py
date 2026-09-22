import json
import os
from urllib import request


def alert(message: str, level: str = "info") -> bool:
    """Send an alert when configured; return False rather than breaking trading."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    prefixes = {"info": "INFO", "warning": "WARNING", "error": "ERROR"}
    payload = json.dumps({"chat_id": chat_id, "text": f"[{prefixes.get(level, 'INFO')}] {message}"}).encode()
    request.urlopen(request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                    data=payload, headers={"Content-Type": "application/json"}), timeout=5)
    return True