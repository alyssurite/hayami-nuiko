"""Filter functions module"""
import os

# telegram core bot api
from telegram import Chat, Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, ContextTypes

# database getters
from ..db.getters import check_channel, check_user


async def filter_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Essentially this function provides a ban."""
    chat_id = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE and await check_user(chat_id):
        return
    if update.effective_chat.type == Chat.CHANNEL and await check_channel(chat_id):
        return
    if chat_id == int(os.environ["USER_ID"]):
        return
    raise ApplicationHandlerStop
