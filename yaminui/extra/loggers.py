"""Loggers module"""

import logging
import os
import sys

# reading setings
import tomllib

from datetime import datetime
from logging import FileHandler, Formatter, Logger
from pathlib import Path
from typing import Optional

# logtail for logging
from logtail import LogtailHandler

# env variables
from yaminui.extra.settings import bot_settings

# current timestamp & app directory
DATE_RUN = datetime.now()
FILE_DIR = Path(__file__).parent.parent.parent  # /extra -> /yoiyoi -> /app


# get config
CONFIG = tomllib.load(Path(bot_settings.log_settings_file).open("rb"))

# set basic config to logger
logging.basicConfig(
    format=CONFIG["log"]["form"],
    level=CONFIG["log"]["level"],
)

# get root logger
root_log = logging.getLogger()


def get_file_handler() -> Optional[FileHandler]:
    """Create file handler"""
    file_log = CONFIG["log"]["file"]
    if file_log["enable"]:
        root_log.info("Logging to file enabled.")
        log_dir = FILE_DIR / file_log["path"]
        if not log_dir.is_dir():
            root_log.warning("Log directory doesn't exist.")
            try:
                root_log.info("Creating log directory...")
                log_dir.mkdir()
                root_log.info("Created log directory: %r.", log_dir.resolve())
            except IOError as ex:
                root_log.error("Exception occured: %s.", ex)
                root_log.info("Can't execute program.")
                sys.exit()
        log_date = DATE_RUN.strftime(file_log["date"])
        log_name = f"{file_log['pref']}{log_date}.log"
        log_file = log_dir / log_name
        root_log.info("Logging to file: %r.", log_name)
        # add file handler
        file_handler = FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(Formatter(file_log["form"]))
        file_handler.setLevel(file_log["level"])
        return file_handler
    root_log.info("Logging to file disabled.")
    return


FILE_HANDLER = get_file_handler()


def get_logtail_handler() -> Optional[LogtailHandler]:
    """Create logtail handler"""
    if token := os.environ.get("LOGTAIL_TOKEN", None):
        return LogtailHandler(token)


LOGTAIL_HANDLER = get_logtail_handler()


# add handlers to root logger
def add_handlers(logger: Logger):
    if FILE_HANDLER:
        logger.addHandler(FILE_HANDLER)
    if LOGTAIL_HANDLER:
        logger.addHandler(LOGTAIL_HANDLER)


add_handlers(root_log)


# setup loggers
def setup_loggers():
    for module in CONFIG["log"]["lib"]:
        logger = logging.getLogger(module["name"])
        if module["enable"]:
            logger.setLevel(module["level"])
        else:
            logger.propagate = False


setup_loggers()
