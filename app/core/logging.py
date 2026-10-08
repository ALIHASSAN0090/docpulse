import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord already has. Anything else on a record came from `extra={...}`.
# ("color_message" is added by uvicorn; we don't want it in our JSON.)
_DUMMY_RECORD = logging.LogRecord("", 0, "", 0, "", None, None)
_STANDARD_ATTRS: set[str] = set(vars(_DUMMY_RECORD)) | {"message", "asctime", "color_message"}

class JsonFormatter(logging.Formatter):
    def format(self , record: logging.LogRecord) -> str: 
        payload: dict[str , Any] = {
            "timestamp": datetime.fromtimestamp(record.created , tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Copy custom fields passed via logger.info("...", extra={"chunk_count": 5})
        for key , value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exec_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload , default=str)

def setup_logging(level: str , fmt: str) -> None:
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))

        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(getattr(logging, level.upper()))

        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True