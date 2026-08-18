"""Main Application"""

import os

import structlog
import uvicorn

# telegram core bot api
from telegram import Update

# the api
from yaminui.app.api import api_application

# the bot
from yaminui.app.bot import bot_application

# get bot modes and constants
from yaminui.bot import BotMode, on_bot_init, on_bot_stop

# env variables
from yaminui.extra.settings import bot_settings

# get logger
log = structlog.get_logger(__name__)


async def start_app(mode: int = BotMode.WEBHOOK):
    """Start main application.

    Args:
        mode (int, optional): bot mode. Defaults to BotMode.WEBHOOK.
    """
    # create web server
    web_server = uvicorn.Server(
        config=uvicorn.Config(
            app=api_application,
            host="0.0.0.0",
            port=bot_settings.private_port,
            log_config=None,
        )
    )
    # run bot and web server together
    async with bot_application:
        await bot_application.initialize()
        await on_bot_init(bot_application)
        await bot_application.start()
        if (hook_url := os.environ.get("HOOK_URL")) and mode == BotMode.WEBHOOK:
            log.info("Running in webhook mode!")
            hook = f"https://{hook_url}:{bot_settings.port}/{bot_settings.token}"
            log.info("Webhook URL | PORT: %s | %s.", hook, bot_settings.port)
            await bot_application.bot.set_webhook(hook, allowed_updates=Update.ALL_TYPES)
        else:
            log.info("Running in polling mode!")
            await bot_application.updater.start_polling()
        await web_server.serve()
        await bot_application.stop()
        await on_bot_stop(bot_application)
