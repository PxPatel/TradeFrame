import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "run_id"):
            payload["run_id"] = record.run_id
        if hasattr(record, "extra_payload"):
            payload.update(record.extra_payload)
        return json.dumps(payload, sort_keys=True)


def configure_logging(log_path: str | Path = "logs/trading.log") -> logging.Logger:
    logger = logging.getLogger("tradeframe")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(path, when="midnight", backupCount=30)
    file_handler.setFormatter(formatter)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
