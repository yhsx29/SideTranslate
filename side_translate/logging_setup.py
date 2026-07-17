from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import APP_DIR


LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"


def setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    if not any(isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers):
        handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=1_048_576,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    def log_uncaught_exception(exception_type, exception, traceback) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception, traceback)
            return
        logging.getLogger("side_translate").critical(
            "uncaught_exception", exc_info=(exception_type, exception, traceback)
        )

    sys.excepthook = log_uncaught_exception
    return LOG_PATH
