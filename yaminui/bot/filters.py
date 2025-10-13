"""Filter functions module"""

# telegram core bot api
from telegram import Chat, Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, ContextTypes

# database getters
from yaminui.db.getters import check_channel, check_user

# env variables
from yaminui.extra.settings import bot_settings


async def filter_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Essentially this function provides a ban."""
    chat_id = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE and await check_user(chat_id):
        return
    if update.effective_chat.type == Chat.CHANNEL and await check_channel(chat_id):
        return
    if chat_id == int(bot_settings.user_id):
        return
    raise ApplicationHandlerStop
