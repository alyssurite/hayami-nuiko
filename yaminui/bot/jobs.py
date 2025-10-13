"""Bot Jobs"""

# http requests
import httpx
import structlog

# telegram core bot api extension
from telegram.ext import ContextTypes

# get fake headers & retry requests
from yaminui.extra import FAKE_HEADERS

# env variables
from yaminui.extra.settings import bot_settings

# setup logger
log = structlog.get_logger(__name__)


async def health_checker(
    context: ContextTypes.DEFAULT_TYPE,
):
    """Ping the specified instance and log the result"""
    logger = log.bind(api="ping_instance")
    if not (hcu := bot_settings.health_check_url):
        return

    health_check = hcu.unicode_string()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            if (
                response := await client.get(
                    health_check,
                    headers=FAKE_HEADERS,
                )
            ).is_error:
                logger.warning(
                    "Failed to reach %s. Status: %s",
                    health_check,
                    response.status_code,
                )
            else:
                logger.debug(
                    "Successfully reached %s. Status: %s",
                    health_check,
                    response.status_code,
                )
    except Exception as ex:
        logger.warning("Exception %s: %s.", ex.__class__.__name__, ex)
