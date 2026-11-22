"""Helpers module"""

import re
import time

from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urlparse

import structlog

# psql exceptions
from psycopg.errors import UniqueViolation

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
from yaminui.api import LinkType, PixivStyle, TwitterStyle

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
log = structlog.get_logger(__name__)


async def check_if_owned(channel_id: int):
    with Session() as session:
        chan = session.get(Channel, channel_id)
        owned = bool(chan and chan.admin)
    log.debug(
        "Ownership check done.",
        channel_id=channel_id,
        exists_in_db=chan is not None,
        owned=owned,
    )
    return owned


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
    user_id = update.effective_chat.id
    clog = log.bind(user_id=user_id)
    clog.debug("Channel check started.")
    forward_origin = update.effective_message.forward_origin
    if not forward_origin:
        await send_error(update, "This message is not forwarded\\.")
        clog.info("Channel rejected: message is not forwarded.")
        return
    if forward_origin.type != MessageOrigin.CHANNEL:
        await send_error(update, "This message is not from channel\\.")
        clog.info(
            "Channel rejected: message is not from a channel.",
            origin_type=str(forward_origin.type),
        )
        return
    forward_origin_channel: MessageOriginChannel = forward_origin
    if not (channel := forward_origin_channel.chat):
        await send_error(update, "This channel is not available\\.")
        clog.warning("Channel rejected: forward origin has no chat info.")
        return
    clog = clog.bind(channel_id=channel.id, channel_title=channel.title)
    if await check_if_owned(channel.id):
        await send_error(update, "This channel is *already* owned\\.")
        clog.info("Channel rejected: already owned by another user.")
        return
    try:
        if not (bot := await channel.get_member(context.bot.id)):
            await send_error(
                update,
                "The bot *is not a member* of this channel of this channel\\!",
            )
            clog.warning("Channel rejected: bot is not a member.")
            return
    except Forbidden:
        await send_error(
            update,
            "The bot *was kicked* from this channel\\!",
        )
        clog.warning("Channel rejected: bot was kicked from the channel.")
        return
    # done with basic checks
    await send_reply(
        update,
        "*Seems fine\\!* ✨\nChecking for *bot admin rights*\\.\\.\\.",
    )
    clog.info("Channel passed basic checks, checking admin rights.")
    if bot.status != CMS.ADMINISTRATOR:
        await send_error(
            update,
            "The bot *is not an admin* of this channel\\!",
        )
        clog.warning("Channel rejected: bot is not an admin.", bot_status=str(bot.status))
        return
    bot_admin: ChatMemberAdministrator = bot
    if not bot_admin.can_post_messages:
        await send_error(
            update,
            "The bot *can't post* in this channel\\!",
        )
        clog.warning("Channel rejected: bot admin lacks can_post_messages right.")
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
        clog.warning(
            "Channel rejected: user is not an admin or owner of the channel.",
            user_status=str(admin.status) if admin else None,
        )
        return
    # done with admin bot checks
    await send_reply(
        update,
        "*Alright\\!* 💫\nAdding *your channel* to the *database*\\.\\.\\.",
    )
    # add channel to database
    with Session.begin() as session:
        # get current user
        user = session.get(User, user_id)
        # remove old channel
        if db_channel := session.get(Channel, channel.id):
            # channel already exist
            clog.debug("Channel already in database, reattaching to user.")
            user.channel = db_channel
        else:
            # channel doesn't exist
            clog.debug("Channel not in database, creating a new record.")
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
    clog.info("Channel successfully added to database.")
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
            log.debug("Pixiv Save: cleared last info.", user_id=user_id)
            return
        art["message_id"] = update.effective_message.message_id
        # JSON column can't store datetime objects — convert to ISO 8601 string
        if isinstance(art.get("date"), datetime):
            art["date"] = art["date"].isoformat()
        user.last_info = art
        log.info(
            "Pixiv Save: stored last info.",
            user_id=user_id,
            art_id=art.get("id"),
            art_type=str(art.get("type")),
            links=len(art.get("links", [])),
        )
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
    started = time.perf_counter()
    art = data.info
    plog = log.bind(
        user_id=update.effective_user.id,
        art_id=art["id"],
        art_type=str(art["type"]),
        channel_id=data.chan,
    )
    plog.info(
        "Post: started.",
        forward=data.forward,
        reply=data.reply,
        above=above,
        links=len(art["links"]),
    )
    if not (ids := await normalize_order(update, text, len(art["links"]))):
        plog.info("Post: aborted, no valid selection.", text=text)
        return PostingResult.STATE_ERROR
    plog = plog.bind(order=list(ids))
    # save for reuse
    art_dict = {
        "aid": art["id"],
        "type": art["type"],
        "files": await extract_media_ids(art),
    }
    if art["type"] == LinkType.TWITTER and len(art_dict["files"]) != len(art["links"]):
        plog.warning(
            "Post: Twitter files count mismatch.",
            files=len(art_dict["files"]),
            links=len(art["links"]),
        )
    post_dict = {
        "channel_id": data.chan,
        "is_original": False,
        "is_forwarded": False,
    }
    if not (artwork := await get_artwork(art["id"], art["type"])):
        notify(update, art=art)
        artwork = ArtWork(**art_dict)
        post_dict["is_original"] = True
        plog.info("Post: new ArtWork, will insert.", files=len(art_dict["files"]))
        plog.debug("Post: ArtWork payload.", art_dict=art_dict)
    else:
        plog.info(
            "Post: reusing existing ArtWork.",
            artwork_id=artwork.id,
            known_files=len(artwork.files or []),
            new_files=len(art_dict["files"]),
        )
        if not artwork.files or len(artwork.files) < len(art_dict["files"]):
            plog.debug("Post: updating ArtWork files with a more complete set.")
            artwork.files = art_dict["files"]
    is_twitter = art["type"] == LinkType.TWITTER
    style = data.twitter if is_twitter else data.pixiv
    if data.forward:
        if posted := await send_media(
            context=context,
            info=art,
            order=ids,
            style=style,
            chat_id=data.chan,
            above=above,
        ):
            plog.info("Post: sent to channel.")
            if is_twitter:
                if data.twitter != TwitterStyle.LINK:
                    posted = posted[0]
            else:
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
                    session.add(
                        Post(
                            **post_dict,
                            artwork=session.merge(artwork) if artwork.id else artwork,
                        )
                    )
                plog.info("Post: inserted Post record.", post_dict=post_dict)
            except IntegrityError as err:
                plog.warning(
                    "Post: integrity error on insert.",
                    error=str(err.orig),
                    unique_violation=isinstance(err.orig, UniqueViolation),
                )
                if isinstance(err.orig, UniqueViolation):
                    plog.info("Post: ArtWork was inserted concurrently, retrying.")
                    if not (artwork := await get_artwork(art["id"], art["type"])):
                        # unique violation but the row is gone: inconsistent state
                        plog.error(
                            "Post: unique violation, but ArtWork can't be found. "
                            "Post is in the channel, but not in the database.",
                            post_dict=post_dict,
                        )
                    else:
                        if not artwork.files or len(artwork.files) < len(
                            art_dict["files"]
                        ):
                            artwork.files = art_dict["files"]
                        plog.info(
                            "Post: using already present ArtWork.",
                            artwork_id=artwork.id,
                        )
                        with Session.begin() as session:
                            session.add(Post(**post_dict, artwork=session.merge(artwork)))
                        plog.info(
                            "Post: inserted Post record on retry.",
                            post_dict=post_dict,
                        )
                else:
                    plog.warning(
                        "Post: not a unique violation, Post record not saved.",
                        post_dict=post_dict,
                    )
            if data.reply:
                if not is_twitter:
                    if data.pixiv not in (
                        PixivStyle.INFO_LINK,
                        PixivStyle.INFO_EMBED_LINK,
                    ):
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
            if is_twitter and data.media and data.twitter == TwitterStyle.LINK:
                await send_media_doc(
                    context=context,
                    info=art,
                    media_filter=("video", "animated_gif", "ugoira"),
                    channel_mode=True,
                    chat_id=data.chan,
                    reply_to_message_id=posted.message_id,
                )
        else:
            await send_error(update, "Coudn't post\\!")
            plog.warning("Post: send_media returned nothing, couldn't post to channel.")
            return PostingResult.STATE_ERROR
    else:
        plog.debug("Post: forwarding disabled, replying only to the user.")
        if data.reply:
            await send_media(
                context=context,
                info=art,
                order=ids,
                style=style,
                chat_id=update.effective_chat.id,
                reply_to_message_id=update.effective_message.message_id,
                above=above,
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
    plog.debug("Post: uploading media to cloud.")
    await upload_media(art, update.effective_chat.id, ids)
    plog.info(
        "Post: finished.",
        is_original=post_dict["is_original"],
        elapsed=round(time.perf_counter() - started, 3),
    )
    return PostingResult.STATE_POSTED


async def normalize_order(
    update: Update,
    text: str,
    count: int,
    max_amount: int = 10,
) -> tuple[int]:
    ids = []
    if not (text and count):
        log.debug("Normalize Order: nothing to parse.", has_text=bool(text), count=count)
        return tuple(ids)
    log.debug("Normalize Order: parsing.", text=text, count=count, max_amount=max_amount)
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
    if not ids:
        log.info("Normalize Order: no numbers found in text.", text=text)
        await send_error(
            update,
            f"No numbers found, expected range: \\[`1`\\-`{count}`\\]\\!",
        )
        return tuple()
    # check if all numbers within range
    if max(ids) > count or min(ids) < 1:
        await send_error(
            update,
            f"*Not within* range: \\[`1`\\-`{count}`\\]\\!",
        )
        log.info(
            "Normalize Order: selection out of range.",
            ids=ids,
            allowed_min=1,
            allowed_max=count,
        )
        return tuple()
        # return tuple(filter(lambda x: 1 <= x <= count, ids))[:max_amount]
    # check if there's more than 10 numbers
    if len(ids) > max_amount:
        await send_error(
            update,
            f"You *can't* choose more than {max_amount} files\\!",
        )
        log.info(
            "Normalize Order: too many files selected.",
            selected=len(ids),
            max_amount=max_amount,
        )
        return tuple()
        # return tuple(ids[:max_amount])
    log.info("Normalize Order: parsed selection.", ids=ids)
    return tuple(ids)


HTTP_LINK_REGEX = re.compile(r"""(?x)
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
    """)
TG_LINK_REGEX = re.compile(r"tg://(?:(?:resolve\?)|(?:privatepost\?))")


async def check_post(update: Update, args: list[str]):
    user_id = update.effective_user.id
    clog = log.bind(user_id=user_id)
    if not args:
        clog.info("Check Post: no arguments provided.")
        await send_error(
            update,
            "No info to get info about\\. You need to provide a link "
            "Use this command like this:\n"
            "`/info https://t.me/ura_kartinki/12991`",
        )
        return
    clog.debug("Check Post: started.", args=args)
    for arg in args:
        earg = esc(arg)
        post_id = None
        channel = None
        if match := re.search(HTTP_LINK_REGEX, arg):
            # http://t.me/c/1183548293/60363
            # https://t.me/denkou/60363
            clog.info("Check Post: found http post link.", arg=arg)
            post_id = int(match.group("post"))
            if not (
                channel_link := match.group("channel_id") or match.group("channel_link")
            ):
                clog.warning("Check Post: no channel info found in link.", arg=arg)
                await send_error(update, f"No channel info found in link: {earg}")
                continue
            channel = await get_channel_by_link(channel_link)
        elif match := re.search(TG_LINK_REGEX, arg):
            # tg://resolve?domain=denkou&post=60363
            # tg://privatepost?channel=1183548293&post=60363
            clog.info("Check Post: found tg post link.", arg=arg)
            url = urlparse(arg)
            query = parse_qs(url.query)
            if post_id := query.get("post"):
                try:
                    post_id = int(post_id[0])
                except ValueError:
                    clog.info(
                        "Check Post: post id in tg link is not an integer.",
                        arg=arg,
                        post_id=post_id[0],
                    )
                    await send_error(
                        update, f"Couldn't convert post id to integer: {earg}"
                    )
                    continue
            if channel_link := query.get("domain") or query.get("channel"):
                channel = await get_channel_by_link(channel_link[0])
        else:
            clog.debug("Check Post: not a link, assuming post id.", arg=arg)
            try:
                post_id = int(arg)
            except ValueError:
                clog.info("Check Post: unknown type of argument.", arg=arg)
                await send_error(update, f"Unknown type of argument: {earg}")
                continue
            if not (channel := await get_user_channel(user_id)):
                clog.info("Check Post: user has no channel attached.", arg=arg)
                await send_error(
                    update,
                    "Assumed you have channel attached, but none found\\. "
                    f"Argument passed as your channel's post id: {earg}",
                )
                continue
        if not (post_id and channel):
            if not post_id:
                clog.info("Check Post: couldn't get post id.", arg=arg)
                await send_error(update, f"Couldn't get post id: {earg}")
            if not channel:
                clog.info("Check Post: couldn't get channel info.", arg=arg)
                await send_error(update, f"Couldn't get channel info: {earg}")
            continue
        clog.debug("Check Post: resolved.", channel_id=channel.id, post_id=post_id)
        if not (post := await get_post_by_uix_post(channel.id, post_id)):
            clog.info(
                "Check Post: no post found.", channel_id=channel.id, post_id=post_id
            )
            await send_error(
                update,
                "No post found\\! Please send the link to the first picture\\.",
            )
            continue
        clog.debug("Check Post: post found.", post_record_id=post.id)
        yield post
    return


async def delete_post_from_everywhere(post_record_id: int, user_id: int):
    """Deletes post from database and from its channel

    Returns:
        int: 0 - success, 1 - post not found, 2 - channel deletion failed,
        3 - channel not found or not owned by the user
    """
    started = time.perf_counter()
    dlog = log.bind(post_record_id=post_record_id, user_id=user_id)
    dlog.info("Delete Post: started.")
    if not (post := await get_post(post_record_id)):
        dlog.info("Delete Post: post wasn't found.")
        return 1
    dlog = dlog.bind(channel_id=post.channel_id, post_id=post.post_id)
    if not (channel := await get_user_channel(user_id)):
        dlog.warning("Delete Post: user has no channel attached.")
        return 3
    if channel.id != post.channel_id:
        # a user trying to delete a post from somebody else's channel
        dlog.warning(
            "Delete Post: post belongs to a different channel than user's.",
            user_channel_id=channel.id,
        )
        return 3
    messages: list[Message] = await pyro_app.get_messages(
        post.channel_id,
        range(post.post_id, post.post_id + 10),
    )
    dlog.debug("Delete Post: fetched messages.", fetched=len(messages))
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
    dlog.debug(
        "Delete Post: resolved messages to delete.",
        message_ids=delete_messages,
        media_group_id=media_group_id or None,
    )
    # delete from db
    with Session.begin() as session:
        session.delete(post)
    dlog.info("Delete Post: deleted from database.")

    # delete from channel
    try:
        affected = await pyro_app.delete_messages(post.channel_id, delete_messages)
    except MessageDeleteForbidden:
        dlog.warning(
            "Delete Post: bot isn't allowed to delete messages in the channel. "
            "Record is removed from database, but messages remain in the channel.",
            message_ids=delete_messages,
        )
        return 2
    except RPCError as error:
        # unexpected telegram failure, database and channel are now out of sync
        dlog.error(
            "Delete Post: telegram error while deleting. "
            "Record is removed from database, but messages may remain in the channel.",
            message_ids=delete_messages,
            error=repr(error),
            exc_info=True,
        )
        return 2
    if affected == len(delete_messages):
        dlog.info("Delete Post: deleted from channel.", deleted=affected)
    else:
        dlog.warning(
            "Delete Post: deleted fewer messages than requested.",
            deleted=affected,
            requested=len(delete_messages),
            message_ids=delete_messages,
        )
    dlog.info("Delete Post: finished.", elapsed=round(time.perf_counter() - started, 3))
    return 0
