"""Filter functions module"""
import os

# telegram core bot api
from telegram import Chat, Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, CallbackContext

# database getters
from ..db.getters import get_channel, get_user


async def filter_out(update: Update, context: CallbackContext):
    """Essentially this function provides a ban."""
    chat_id = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE and await get_user(chat_id):
        return
    if update.effective_chat.type == Chat.CHANNEL and await get_channel(chat_id):
        return
    if chat_id == int(os.environ["USER_ID"]):
        return
    raise ApplicationHandlerStop
