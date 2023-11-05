"""Commands module"""
import logging
import os

from pathlib import Path

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import CallbackContext, ConversationHandler

# pixiv & twiter styles
from ..api import PixivStyle, TwitterStyle

# database updaters
from ..db.updaters import update_chat

# bot states
from . import BotState

# bot loggers
from .loggers import notify

# bot senders
from .senders import send_error, send_reply

# bot switchers
from .switchers import change_style, toggler

# get logger
log = logging.getLogger(__name__)

# get help contents
HELP_MESSAGE = Path(os.environ["HELP_FILE"]).read_text(encoding="utf-8")


async def command_start(update: Update, _: CallbackContext) -> None:
    """Sends start message."""
    notify(update, command="/start")
    await update_chat(update.effective_chat)
    await send_reply(
        update,
        f"Hello, {update.effective_chat.mention_markdown_v2()}\\!\n"
        "Nice to meet you\\! My name is *Nuiko Hayami*\\. ❄️\n"
        "Please, see \\/help to learn more about me\\!",
    )


async def command_help(update: Update, _: CallbackContext) -> None:
    """Sends help message."""
    notify(update, command="/help")
    await send_reply(update, text=HELP_MESSAGE)


async def command_forward(update: Update, _: CallbackContext) -> None:
    """Toggles forwarding to channel."""
    notify(update, command="/forward")
    try:
        await toggler(update, mode="Forwarding", field="forward_mode")
    except ValueError:
        await send_error(update, "Set a /channel\\! Can't enable /forward\\.")


async def command_reply(update: Update, _: CallbackContext) -> None:
    """Toggles replying to user's messages."""
    notify(update, command="/reply")
    await toggler(update, mode="Replying", field="reply_mode")


async def command_media(update: Update, _: CallbackContext) -> None:
    """Toggles adding video/gif to bare links."""
    notify(update, command="/media")
    await toggler(update, mode="Media", field="media_mode")


async def command_pixiv_style(update: Update, context: CallbackContext) -> None:
    """Changes (switches/cycles) Pixiv style."""
    notify(update, command="/pixiv_style")
    await change_style(update, style=PixivStyle, args=context.args)


async def command_twitter_style(update: Update, context: CallbackContext) -> None:
    """Changes (switches/cycles) Twitter style."""
    notify(update, command="/twitter_style")
    await change_style(update, style=TwitterStyle, args=context.args)


async def command_channel(update: Update, context: CallbackContext) -> int:
    """Starts process of adding user's channel to database."""
    notify(update, command="/channel")
    if context.user_data.get(BotState.CHANNEL, None):
        await send_reply(
            update,
            "*Ehm\\.\\.\\.*\n" "Please, forward a post from *your channel* already\\.",
        )
        return BotState.CHANNEL
    context.user_data[BotState.CHANNEL] = True
    await send_reply(
        update,
        "*Sure\\!* 💫\n"
        "Please, add *this bot* to *your channel* as admin\\.\n"
        "Then, forward a message from *your channel* to me\\.",
    )
    return BotState.CHANNEL


async def command_cancel(update: Update, context: CallbackContext) -> int:
    """Cancels and ends conversation."""
    notify(update, command="/cancel")
    if context.user_data.get(BotState.CHANNEL, None):
        context.user_data[BotState.CHANNEL] = False
        await send_reply(
            update,
            "*Okay\\!* 👌\nYou can add *your channel* any time\\.",
        )
        return ConversationHandler.END
    await send_reply(
        update,
        "*Yeah, sure\\.* 👀\nCancel all you want\\.",
    )
