import logging
import sys

from pythonjsonlogger.jsonlogger import JsonFormatter

from config import LOG_LEVEL


def setup_logging() -> None:
    """Configure root logger to emit structured JSON on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    root.handlers = [handler]
