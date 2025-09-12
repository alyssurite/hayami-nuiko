"""Bot Jobs"""

import logging
import os

# http requests
import httpx

# telegram core bot api extension
from telegram.ext import ContextTypes

# get fake headers & retry requests
from yaminui.extra import FAKE_HEADERS

# setup logger
log = logging.getLogger(__name__)


async def health_checker(
    context: ContextTypes.DEFAULT_TYPE,
):
    """Ping the specified instance and log the result"""
    if not (hcu := os.getenv("health_check_url")):
        return

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            if (response := await client.get(hcu, headers=FAKE_HEADERS)).is_error:
                log.warning(
                    "PingInstance: Failed to reach %s. Status: %s",
                    hcu,
                    response.status_code,
                )
            else:
                log.debug(
                    "PingInstance: Successfully reached %s. Status: %s",
                    hcu,
                    response.status_code,
                )
    except Exception as ex:
        log.warning("PingInstance: Exception %s: %s.", ex.__class__.__name__, ex)
