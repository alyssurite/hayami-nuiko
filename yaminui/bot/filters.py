"""Filter functions module"""

import functools

# structured logging
import structlog

from structlog.contextvars import bind_contextvars, unbind_contextvars

# telegram core bot api
from telegram import Chat, Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, ContextTypes

# database getters
from yaminui.db.getters import check_channel, check_user

# env variables
from yaminui.extra.settings import bot_settings

log = structlog.get_logger(__name__)


async def filter_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Essentially this function provides a ban."""
    bind_contextvars(update_id=update.update_id)
    chat_id = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE and await check_user(chat_id):
        return
    if update.effective_chat.type == Chat.CHANNEL and await check_channel(chat_id):
        return
    if chat_id == int(bot_settings.user_id):
        return
    unbind_contextvars("update_id")
    raise ApplicationHandlerStop


def clear_context(contextvar_list=None):
    def wrapper(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            result = await func(*args, **kwargs)
            if contextvar_list and isinstance(contextvar_list, list):
                for contextvar in contextvar_list:
                    unbind_contextvars(contextvar)
            else:
                unbind_contextvars("update_id")
            return result

        return wrapped

    return wrapper
