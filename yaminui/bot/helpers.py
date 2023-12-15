"""Helpers module"""
import logging
import os
import re

from typing import Optional

# telegram core bot api
from telegram import Update

# telegram constants
from telegram.constants import ChatMemberStatus as CMS

# telegram errors
from telegram.error import Forbidden

# telegram core bot api extension
from telegram.ext import CallbackContext, ConversationHandler

# pixiv & twitter styles, link types
from ..api import PixivStyle

# database session
from ..db import Session

# database getters
from ..db.getters import get_artwork, get_channel

# database models
from ..db.models import ArtWork, Channel, Post, User

# uploading media
from ..extra.upload import upload_media

# bot states, pixiv number regexp, data dataclass, posting results
from . import BotState, PostingResult, UserData, pixiv_number

# bot loggers
from .loggers import notify

# bot senders
from .senders import send_error, send_media, send_media_doc, send_reply, send_reply_post

# bot utils
from .utils import extract_media_ids

# get logger
log = logging.getLogger(__name__)


async def channel_check(
    update: Update,
    context: CallbackContext,
) -> Optional[int]:
    """Checks if channel is a valid choice

    Args:
        update (Update): current update
        context (CallbackContext): current context

    Returns:
        Optional[int]: ConversationHandler state
    """
    if chat := update.effective_message.forward_from_chat:
        if chat.type == "supergroup":
            await send_error(update, "This message is from a supergroup\\.")
            log.error("Channel: This message is from a supergroup.")
            return
        with Session() as session:
            if (chan := session.get(Channel, chat.id)) and chan.admin:
                await send_error(update, "This channel is *already* owned\\.")
                log.error("Channel: [%s] is already owned.", chat.id)
                return
        await send_reply(
            update,
            "*Seems fine\\!* ✨\nChecking for *admin rights*\\.\\.\\.",
        )
        bot_id = int(os.getenv("TOKEN").split(":")[0])
        user_id = update.effective_chat.id
        try:
            if not (
                (bot := await chat.get_member(bot_id))
                and bot.status == CMS.ADMINISTRATOR
                and bot.can_post_messages
            ):
                await send_error(
                    update,
                    "The bot *is not an admin* of this channel or *can't post*"
                    " in this channel\\!",
                )
                log.error("Channel: No appropriate admin rights for bot.")
                return
        except Forbidden:
            await send_error(
                update,
                "The bot *was kicked* from this channel\\!",
            )
            log.error("Channel: The bot was kicked from this channel.")
            return
        if not (
            (admin := await chat.get_member(user_id))
            and admin.status in (CMS.OWNER, CMS.ADMINISTRATOR)
        ):
            await send_error(
                update,
                "You *are not an admin* of this channel\\!",
            )
            log.error("Channel: No admin rights for user.")
            return
        with Session.begin() as session:
            # get current user
            user = session.get(User, user_id)
            # remove old channel
            if chan:
                # channel already exist
                user.channel = chan
            else:
                # channel doesn't exist
                user.channel = None
                # create new channel
                session.add(
                    Channel(
                        id=chat.id,
                        name=chat.title,
                        link=chat.username,
                        is_admin=True,
                        admin=user,
                    )
                )
        # remove from banned list
        await get_channel.cache.set(chat.id, True)
        await send_reply(
            update,
            "*Done\\!* 🎉\n*Your channel* is added to the database\\!",
        )
        del context.user_data[BotState.CHANNEL]
        return ConversationHandler.END
    await send_error(
        update,
        "Please, *forward* a message from *your channel*\\.",
    )
    log.error("Channel: This message is from a user.")
    return


async def pixiv_save(update: Update, art: dict = None) -> None:
    """Saves current art media data to user's last_info

    Args:
        update (Update): current update
        art (dict, optional): art media dictionary. Defaults to None
    """
    notify(update.effective_chat, function="pixiv_save")
    user_id = update.effective_user.id
    with Session.begin() as session:
        user = session.get(User, user_id)
        if art is None:
            user.last_info = None
            log.info("Pixiv Save: Deleted last info from user <%d>.", user_id)
            return
        art["message_id"] = update.effective_message.message_id
        user.last_info = art
        log.info("Pixiv Save: Added last info to user <%d>.", user_id)
    # prompt user to choose illustrations
    await send_reply(
        update,
        "Please, choose illustrations to download\\: "
        f'\\[`1`\\-`{len(art["links"])}`\\]\\.',
    )


async def pixiv_post(
    update: Update,
    context: CallbackContext,
    data: UserData,
    text: str,
) -> None:
    notify(update.effective_chat, function="pixiv_post")
    art = data.info
    if not (ids := await normalize_order(update, text, len(art["links"]))):
        return PostingResult.STATE_ERROR
    # save for reuse
    art_dict = {
        "aid": art["id"],
        "type": art["type"],
        "files": await extract_media_ids(art),
    }
    post_dict = {
        "channel_id": data.chan,
        "is_original": False,
        "is_forwarded": False,
    }
    if not (artwork := await get_artwork(art["id"], art["type"])):
        notify(update.effective_chat, art=art)
        artwork = ArtWork(**art_dict)
        post_dict["is_original"] = True
        log.info("Pixiv Post: ArtWork to insert: %s.", art_dict)
    else:
        log.info("Pixiv Post: Used ArtWork: %s.", art_dict)
    if data.forward:
        if posted := await send_media(
            context=context,
            info=art,
            order=ids,
            style=data.pixiv,
            chat_id=data.chan,
        ):
            log.info("Pixiv Post: Successfully posted to channel.")
            if data.pixiv not in (
                PixivStyle.INFO_LINK,
                PixivStyle.INFO_EMBED_LINK,
            ):
                posted = posted[0]
            post_dict.update(
                {
                    "post_id": posted.message_id,
                    "post_date": posted.date,
                }
            )
            with Session.begin() as session:
                session.add(Post(**post_dict, artwork=artwork))
            log.info("Pixiv Post: Inserted Post: %s.", post_dict)
            if data.reply:
                await send_media(
                    context=context,
                    info=art,
                    order=ids,
                    style=data.pixiv,
                    chat_id=update.effective_chat.id,
                    reply_to_message_id=update.effective_message.message_id,
                )
                await send_reply_post(
                    update,
                    "posted",
                    data.chan,
                    posted.message_id,
                    art["link"],
                )
        else:
            await send_error(update, "Coudn't post\\!")
            log.error("Pixiv Post: Couldn't post.")
            return PostingResult.STATE_ERROR
    else:
        if data.reply:
            await send_media(
                context=context,
                info=art,
                order=ids,
                style=data.pixiv,
                chat_id=update.effective_chat.id,
                reply_to_message_id=update.effective_message.message_id,
            )
        await send_media_doc(
            context=context,
            info=art,
            order=ids,
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.message_id,
        )
    # clean last_info for user
    await pixiv_save(update)
    # upload to cloud
    await upload_media(art, update.effective_chat.id, ids)
    return PostingResult.STATE_POSTED


async def normalize_order(
    update: Update,
    text: str,
    count: int,
    max_amount: int = 10,
) -> tuple[int]:
    ids = []
    if not (text and count):
        return tuple(ids)
    for number in re.finditer(pixiv_number, text):
        n1 = int(number.group("n1"))
        if n2 := number.group("n2"):
            n2 = int(n2)
        else:
            n2 = n1
        if n1 > n2:
            ids += reversed(range(n2, n1 + 1))
        else:
            ids += range(n1, n2 + 1)
    ids = list(dict.fromkeys(ids))  # can't use set() because of order
    # check if all numbers within range
    if max(ids) > count or min(ids) < 1:
        await send_error(
            update,
            f"*Not within* range: \\[`1`\\-`{count}`\\]\\!",
        )
        log.error("Normalize Order: Not within range [1-%s].", count)
        return tuple()
        # return tuple(filter(lambda x: 1 <= x <= count, ids))[:max_amount]
    # check if there's more than 10 numbers
    if len(ids) > max_amount:
        await send_error(
            update,
            f"You *can\\'t* choose more than {max_amount} files\\!",
        )
        log.error("Normalize Order: More than %s files.", max_amount)
        return tuple()
        # return tuple(ids[:max_amount])
    log.info("Normalize Order: Result: %s.", ids)
    return tuple(ids)
