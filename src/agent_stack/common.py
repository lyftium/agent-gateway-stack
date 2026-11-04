"""Request ids, structured logs and build lineage shared by all services."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from functools import lru_cache

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id(incoming: str | None) -> str:
    """Reuse a caller's id only if it is short and log-safe; otherwise mint one."""
    if incoming and _REQUEST_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


class _StdoutHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout.write(self.format(record) + "\n")


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(_StdoutHandler())
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    logger.info(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}, sort_keys=True))


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=1)
def git_sha() -> str:
    if sha := os.environ.get("GIT_SHA"):
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
