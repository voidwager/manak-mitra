"""Minimal structured-ish logging setup.

Deliberately simple. When we move to on-premise deployment this is the one
place that needs to change to emit JSON lines to the plant's log collector.
"""

import logging
import sys

from app.core.config import settings

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers when uvicorn reloads.
    if not any(getattr(h, "_synq", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._synq = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.sql_echo else logging.WARNING
    )

    # The HTTP client logs every TLS handshake and header at DEBUG. One chat
    # turn now makes several provider calls - capability discovery, a tool
    # round, the answer - so with DEBUG=true this buries the application's
    # own lines under transport chatter, and headers include Set-Cookie and
    # rate-limit values nobody wants in a plant log file.
    #
    # Their INFO lines (one per request) are genuinely useful, so they are
    # pinned there rather than silenced.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
