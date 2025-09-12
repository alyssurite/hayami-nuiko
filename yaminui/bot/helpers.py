"""Helpers module"""

import logging
import re

from typing import Optional
from urllib.parse import parse_qs, urlparse

# psql exceptions
from psycopg2.errors import UniqueViolation

# pyrogram errors
from pyrogram.errors import MessageDeleteForbidden, RPCError

# pyrogram types
from pyrogram.types import Message

# sqlaclhemy exceptions
from sqlalchemy.exc import IntegrityError

# telegram core bot api
from telegram import ChatMemberAdministrator, MessageOrigin, MessageOriginChannel, Update

# telegram constants
from telegram.constants import ChatMemberStatus as CMS

# telegram errors
from telegram.error import Forbidden

# telegram core bot api extension
from telegram.ext import ContextTypes, ConversationHandler

# pixiv & twitter styles, link types
from yaminui.api import PixivStyle

# bot state, results, user data, etc.
from yaminui.bot import BotState, PostingResult, UserData, esc, pixiv_number, pyro_app

# bot loggers
from yaminui.bot.loggers import notify

# bot senders
from yaminui.bot.senders import (
    send_error,
    send_media,
    send_media_doc,
    send_reply,
    send_reply_post,
)

# bot utils
from yaminui.bot.utils import extract_media_ids

# database session
from yaminui.db import Session

# database getters
from yaminui.db.getters import (
    check_channel,
    get_artwork,
    get_channel_by_link,
    get_post,
    get_post_by_uix_post,
    get_user_channel,
)

# database models
from yaminui.db.models import ArtWork, Channel, Post, User

# uploading media
from yaminui.extra.upload import upload_media

# get logger
log = logging.getLogger(__name__)


async def check_if_owned(channel_id: int):
    with Session() as session:
        return bool((chan := session.get(Channel, channel_id)) and chan.admin)


async def channel_check(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[int]:
    """Checks if channel is a valid choice

    Args:
        update (Update): current update
        context (ContextTypes.DEFAULT_TYPE): current context

    Returns:
        Optional[int]: ConversationHandler state
    """
    forward_origin = update.effective_message.forward_origin
    if not forward_origin:
        await send_error(update, "This message is not forwarded\\.")
        log.error("Channel: This message is not forwarded.")
        return
    if forward_origin.type != MessageOrigin.CHANNEL:
        await send_error(update, "This message is not from channel\\.")
        log.error("Channel: This message is not from channel.")
        return
    forward_origin_channel: MessageOriginChannel = forward_origin
    if not (channel := forward_origin_channel.chat):
        await send_error(update, "This channel is not available\\.")
        log.error("Channel: This channel is not available.")
        return
    if await check_if_owned(channel.id):
        await send_error(update, "This channel is *already* owned\\.")
        log.error("Channel: [%s] is already owned.", channel.id)
        return
    try:
        if not (bot := await channel.get_member(context.bot.id)):
            await send_error(
                update,
                "The bot *is not a member* of this channel of this channel\\!",
            )
            log.error("Channel: The bot is not a member of this channel.")
            return
    except Forbidden:
        await send_error(
            update,
            "The bot *was kicked* from this channel\\!",
        )
        log.error("Channel: The bot was kicked from this channel.")
        return
    # done with basic checks
    await send_reply(
        update,
        "*Seems fine\\!* ✨\nChecking for *bot admin rights*\\.\\.\\.",
    )
    log.info("Channel: [%s] passed basic checks. Checking admin rights...", channel.id)
    if bot.status != CMS.ADMINISTRATOR:
        await send_error(
            update,
            "The bot *is not an admin* of this channel\\!",
        )
        log.error("Channel: The bot is not an admin of this channel.")
        return
    bot_admin: ChatMemberAdministrator = bot
    if not bot_admin.can_post_messages:
        await send_error(
            update,
            "The bot *can't post* in this channel\\!",
        )
        log.error("Channel: The bot can't post in this channel.")
        return
    # done with admin bot checks
    if not (
        (admin := await channel.get_member(update.effective_chat.id))
        and admin.status in (CMS.OWNER, CMS.ADMINISTRATOR)
    ):
        await send_error(
            update,
            "You *are not an admin* of this channel\\!",
        )
        log.error("Channel: The user is not an admin in this channel.")
        return
    # done with admin bot checks
    await send_reply(
        update,
        "*Alright\\!* 💫\nAdding *your channel* to the *database*\\.\\.\\.",
    )
    # add channel to database
    with Session.begin() as session:
        # get current user
        user = session.get(User, update.effective_chat.id)
        # remove old channel
        if db_channel := session.get(Channel, channel.id):
            # channel already exist
            user.channel = db_channel
        else:
            # channel doesn't exist
            user.channel = None
            # create new channel
            session.add(
                Channel(
                    id=channel.id,
                    name=channel.title,
                    link=channel.username,
                    is_admin=True,
                    admin=user,
                )
            )
    # remove from banned list
    await check_channel.cache.set(channel.id, True)
    await send_reply(
        update,
        "*Done\\!* 🎉\n*Your channel* is added to the *database*\\!",
    )
    log.info("Channel: [%s] successfully added to database.", channel.id)
    del context.user_data[BotState.CHANNEL]
    return ConversationHandler.END


async def pixiv_save(update: Update, art: dict = None) -> None:
    """Saves current art media data to user's last_info

    Args:
        update (Update): current update
        art (dict, optional): art media dictionary. Defaults to None
    """
    notify(update, function="pixiv_save")
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
        "Please, choose illustrations to download: "
        f'\\[`1`\\-`{len(art["links"])}`\\]\\.',
    )


async def pixiv_post(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: UserData,
    text: str,
    above: bool = False,
) -> None:
    notify(update, function="pixiv_post")
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
        notify(update, art=art)
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
            above=above,
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
            try:
                with Session.begin() as session:
                    session.add(Post(**post_dict, artwork=artwork))
                log.info("Pixiv Post: Inserted Post: %s.", post_dict)
            except IntegrityError as err:
                log.warning("Pixiv Post: Integrity Error occured: %s", err)
                if isinstance(err.orig, UniqueViolation):
                    log.info("Pixiv Post: Seems like artwork is already in database.")
                    if not (artwork := await get_artwork(art["id"], art["type"])):
                        log.error("Pixiv Post: Failed to find artwork in database.")
                        log.error(
                            "Pixiv Post: Failed to insert ArtWork with Post: %s.",
                            post_dict,
                        )
                    else:
                        log.info(
                            "Pixiv Post: Used already present ArtWork: [%d] %s.",
                            artwork.id,
                            art_dict,
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
            f"You *can't* choose more than {max_amount} files\\!",
        )
        log.error("Normalize Order: More than %s files.", max_amount)
        return tuple()
        # return tuple(ids[:max_amount])
    log.info("Normalize Order: Result: %s.", ids)
    return tuple(ids)


HTTP_LINK_REGEX = re.compile(
    r"""(?x)
        t\.me
        \/
        (?:
            (?:c\/(?P<channel_id>\d+))
            |
            (?P<channel_link>[A-Za-z0-9_]+)
        )
        \/
        (?P<post>\d+)
        (?:
            \/
            |
            (?:\?\w+)
        )?
        $
    """
)
TG_LINK_REGEX = re.compile(r"tg://(?:(?:resolve\?)|(?:privatepost\?))")


async def check_post(update: Update, args: list[str]):
    if not args:
        log.error("No info to get info about.")
        await send_error(
            update,
            "No info to get info about\\. You need to provide a link "
            "Use this command like this:\n"
            "`/info https://t.me/ura_kartinki/12991`",
        )
        return
    for arg in args:
        earg = esc(arg)
        if match := re.search(HTTP_LINK_REGEX, arg):
            # http://t.me/c/1183548293/60363
            # https://t.me/denkou/60363
            log.info("Found http post link: %s.", arg)
            post_id = int(match.group("post"))
            if not (
                channel_link := match.group("channel_id") or match.group("channel_link")
            ):
                log.error("No channel info found in link!")
                await send_error(update, f"No channel info found in link: {earg}")
                continue
            channel = await get_channel_by_link(channel_link)
        elif match := re.search(TG_LINK_REGEX, arg):
            # tg://resolve?domain=denkou&post=60363
            # tg://privatepost?channel=1183548293&post=60363
            log.info("Found tg post link: %s.", arg)
            url = urlparse(arg)
            query = parse_qs(url.query)
            if post_id := query.get("post"):
                try:
                    post_id = int(post_id[0])
                except ValueError:
                    log.warning("Couldn't convert to integer.")
                    await send_error(
                        update, f"Couldn't convert post id to integer: {earg}"
                    )
                    continue
            if channel_link := query.get("domain") or query.get("channel"):
                channel = await get_channel_by_link(channel_link[0])
        else:
            log.info("Doesn't look like link: %s.", arg)
            log.info("Assuming it's post id.")
            log.info("Trying to convert to integer...")
            try:
                post_id = int(arg)
            except ValueError:
                log.warning("Couldn't convert to integer.")
                log.error("Unknown type of argument.")
                await send_error(update, f"Unknown type of argument: {earg}")
                continue
            if not (channel := await get_user_channel(update.effective_user.id)):
                await send_error(
                    update,
                    "Assumed you have channel attached, but none found\\. "
                    f"Argument passed as your channel's post id: {earg}",
                )
                continue
        if not (post_id and channel):
            if not post_id:
                log.error("Couldn't get post id!")
                await send_error(update, f"Couldn't get post id: {earg}")
            if not channel:
                log.error("Couldn't get channel info!")
                await send_error(update, f"Couldn't get channel info: {earg}")
            continue
        log.info("Got info: [ %d | %d ].", channel.id, post_id)
        if not (post := await get_post_by_uix_post(channel.id, post_id)):
            await send_error(
                update,
                "No post found\\! Please send the link to the first picture\\.",
            )
            continue
        yield post
    return


async def delete_post_from_everywhere(post_record_id: int, user_id: int):
    if not (post := await get_post(post_record_id)):
        log.error(
            "[%d | %d] Post wasn't found.",
            post_record_id,
            user_id,
        )
        return 1
    if not (channel := await get_user_channel(user_id)):
        log.error(
            "[%d | %d] Channel for user wasn't found.",
            post_record_id,
            user_id,
        )
        return 3
    if channel.id != post.channel_id:
        log.error(
            "[%d | %d] User's channel is different: [%d].",
            post_record_id,
            user_id,
            channel.id,
        )
        return 3
    messages: list[Message] = await pyro_app.get_messages(
        post.channel_id,
        range(post.post_id, post.post_id + 10),
    )
    delete_messages = []
    media_group_id = 0
    for message in messages:
        if not message.media_group_id:
            # no media group = 1 picture, add just 1 post
            if not media_group_id:
                # add only if no media group was defined
                delete_messages.append(message.id)
            break
        elif not media_group_id:
            # no media group yet defined - add post and store media group
            media_group_id = message.media_group_id
            delete_messages.append(message.id)
            continue
        elif media_group_id == message.media_group_id:
            # it's part of stored media group - add post
            delete_messages.append(message.id)
            continue
        # stop if no more images are in media group
        break
    # delete from db
    log.info("Deleting post from database...")
    with Session.begin() as session:
        session.delete(post)
    log.info("Deleted post from database.")

    # delete from channel
    log.info("Deleting posts %s from channel...", delete_messages)
    try:
        affected = await pyro_app.delete_messages(post.channel_id, delete_messages)
        log.info("Deleted posts from channel.")
        if affected == len(delete_messages):
            log.info("Affected check succeeded: %d.", affected)
        else:
            log.error("Affected check failed: %d != %d.", affected, len(delete_messages))
    except MessageDeleteForbidden:
        log.error("The bot can't delete this post!")
        return 2
    except RPCError as error:
        log.error("Some shit happened. %s.", error)
        return 2
    return 0
