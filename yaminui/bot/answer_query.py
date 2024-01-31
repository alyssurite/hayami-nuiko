"""Answer query functions module"""
import logging

# working with timezone
from datetime import timezone as tz
from typing import Optional

# working with URLs
from urllib.parse import unquote

# pyrogram exceptions
from pyrogram.errors.exceptions import BadRequest, ChannelPrivate

# pyrogram types
from pyrogram.types import Message

# telegram core bot api
from telegram import Update

# telegram constants
from telegram.constants import ParseMode as PM

# telegram core bot api extension
from telegram.ext import CallbackContext

# pixiv & twitter styles, link types
from ..api import LinkType, PixivStyle, TwitterStyle

# namedtuples
from ..api.namedtuples import Link

# bot posting
from ..bot.helpers import normalize_order, pixiv_post

# bot utils
from ..bot.utils import cid_to_channel_id

# database session
from ..db import Session

# database getters
from ..db.getters import get_artwork, get_other_links, get_user_data

# database models
from ..db.models import Channel, Post

# uploading media
from ..extra.upload import upload_media

# user data dataclass and everything else
from . import PostingResult, UserData, esc, pyro_app, result_message

# bot helpers
from .helpers import pixiv_save

# bot loggers
from .loggers import notify

# bot senders
from .senders import send_error, send_media, send_media_doc, send_reply_post

# bot utils
from .utils import formatter, get_links

# get logger
log = logging.getLogger(__name__)


async def get_messages_to_repost(
    current_channel_id: int,
    posted_links: list[str],
) -> tuple[int, list[Message]]:
    messages = []
    for post in reversed(posted_links):
        *_, cid, pid = post.split("/")
        channel_id, post_id = cid_to_channel_id(int(cid)), int(pid)
        try:
            if (message := await pyro_app.get_messages(channel_id, int(post_id))).empty:
                log.error("Query Repost: Couldn't repost from %r: No message.", post)
                continue
        except (BadRequest, ChannelPrivate) as err:
            log.error("Query Repost: Couldn't repost from %r: %s.", post, err)
            continue
        messages.append(message)
        if channel_id == current_channel_id or channel_id == message.forward_from_chat:
            log.error("Query Repost: Self-forwarding is not allowed.")
            return (PostingResult.STATE_SELFREPOST, messages)
    return (PostingResult.STATE_CONTINUE, messages)


async def get_source_channel(message: Message) -> Optional[int]:
    if source := (message.forward_from_chat or message.chat):
        with Session() as session:
            if channel := session.get(Channel, source.id):
                log.info(
                    "Query Repost: Source: <%d> %r.",
                    channel.id,
                    channel.name,
                )
                return channel.id
            log.info("Query Repost: Source: Unknown.")
            log.info(
                "Query Repost: Source: Info: <%d> %r.",
                message.chat.id,
                message.chat.title
                if message.chat.id < 0
                else message.chat.first_name + message.chat.last_name,
            )
    return None


async def get_forward_ids(post_id: int, channel_id: int, message: Message) -> list[int]:
    if not (mgi := message.media_group_id):
        return [post_id]
    forward_ids = [post_id]
    for group_post_id in range(post_id + 1, post_id + 11):
        message = await pyro_app.get_messages(channel_id, group_post_id)
        if message.media_group_id != mgi:
            break
        forward_ids.append(group_post_id)
    return forward_ids


async def answer_query_twitter(
    update: Update,
    context: CallbackContext,
    data: UserData,
    art: dict,
    post_dict: dict,
    illust: str = None,
):
    if posted := await send_media(
        context=context,
        info=art,
        style=data.twitter,
        chat_id=data.chan,
        order=(
            await normalize_order(update, illust, len(art["links"])) if illust else None
        ),
    ):
        log.info("Query Post Twitter: Successfully posted to channel.")
        if data.twitter != TwitterStyle.LINK:
            posted = posted[0]
        post_dict.update(
            {
                "post_id": posted.message_id,
                "post_date": posted.date,
            }
        )
        with Session.begin() as session:
            session.add(Post(**post_dict))
        log.info("Query Post Twitter: Inserted Post: %s.", post_dict)
        if data.reply:
            await send_reply_post(
                update,
                "posted",
                data.chan,
                posted.message_id,
                art["link"],
            )
        if data.media and data.twitter == TwitterStyle.LINK:
            await send_media_doc(
                context=context,
                info=art,
                media_filter=("video", "animated_gif", "ugoira"),
                channel_mode=True,
                chat_id=data.chan,
                reply_to_message_id=posted.message_id,
            )
        return PostingResult.STATE_POSTED
    return PostingResult.STATE_ERROR


async def answer_query_pixiv(
    update: Update,
    context: CallbackContext,
    data: UserData,
    art: dict,
    post_dict: dict,
    illust: str = None,
):
    if illust:
        data.info = art
        return await pixiv_post(update, context, data, illust)
    if len(art["links"]) == 1 or data.pixiv in (
        PixivStyle.INFO_LINK,
        PixivStyle.INFO_EMBED_LINK,
    ):
        if posted := await send_media(
            context=context,
            info=art,
            style=data.pixiv,
            chat_id=data.chan,
        ):
            log.info("Query Post Pixiv: Successfully posted to channel.")
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
                session.add(Post(**post_dict))
            log.info("Query Post Pixiv: Inserted Post: %s.", post_dict)
            if data.reply:
                await send_media(
                    context=context,
                    info=art,
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
            return PostingResult.STATE_POSTED
        return PostingResult.STATE_ERROR
    await pixiv_save(update, art)
    return PostingResult.STATE_CONTINUE


def convert_entities_to_links(update: Update):
    links = update.effective_message.entities
    link = unquote(links[0].url)
    posted = [link.url for link in links[1:-3]]
    text = ", and ".join([f"[here]({esc(post)})" for post in posted])
    return link, posted, text


async def answer_query_post(
    update: Update,
    context: CallbackContext,
    data: UserData,
    out: Link = None,
) -> None:
    notify(update, command="answer_query_post")
    result = PostingResult.STATE_NOT_POSTABLE
    # get message info
    if out:
        link = f"{out.link}{'+'+out.illust if out.illust else ''}"
        art_link = out
    else:
        link, _, _ = convert_entities_to_links(update)
        if not (art_link := await formatter(link)):
            log.error("Query Post: Couldn't get content: %r.", link)
            return result
        art_link = art_link[0]
    post_dict = {
        "channel_id": data.chan,
        "is_original": False,
        "is_forwarded": False,
    }
    if not (art := await get_links(art_link)):
        await send_error(
            update,
            f"[This content]({link}) can\\'t be found or downloaded\\!"
            " If this seems to be wrong, try again later\\.",
        )
        log.error("Query Post: Couldn't get content: %r.", link)
        return result
    art = art._asdict()
    illust = art_link.illust or None
    notify(update, art=art)
    # artwork already exists
    post_dict["artwork"] = await get_artwork(art["id"], art["type"])
    match art["type"]:
        case LinkType.TWITTER:
            result = await answer_query_twitter(
                update, context, data, art, post_dict, illust
            )
        case LinkType.PIXIV:
            result = await answer_query_pixiv(
                update, context, data, art, post_dict, illust
            )
    # upload to cloud
    if result == PostingResult.STATE_POSTED:
        await upload_media(art, update.effective_chat.id)
    return result


async def answer_query_repost(
    update: Update,
    context: CallbackContext,
    data: UserData,
    out: Link = None,
) -> None:
    notify(update, command="answer_query_repost")
    result = PostingResult.STATE_NOT_POSTABLE
    # get message info
    if out:
        link = f"{out.link}{'+'+out.illust if out.illust else ''}"
        art_link = out
        posted = await get_other_links(out.id, out.type)
    else:
        link, posted, _ = convert_entities_to_links(update)
        if not (art_link := await formatter(link)):
            log.error("Query Repost: Couldn't get content: %r.", link)
            return result
        art_link = art_link[0]
    repost_dict = {
        "channel_id": data.chan,
        "is_original": False,
        "is_forwarded": True,
        "artwork": await get_artwork(art_link.id, art_link.type),
    }
    messages_to_repost = await get_messages_to_repost(data.chan, posted)
    if messages_to_repost[0] == PostingResult.STATE_SELFREPOST:
        await send_error(update, "You shouldn't *self\\-forward*\\!")
        return PostingResult.STATE_SELFREPOST
    for message in reversed(messages_to_repost[1]):
        repost_dict["forwarded_channel_id"] = await get_source_channel(message)
        forward_ids = await get_forward_ids(message.id, message.chat.id, message)
        log.info(
            "Query Repost: Reposting from <%d>: %s...",
            message.chat.id,
            forward_ids,
        )
        if reposted := await pyro_app.forward_messages(
            repost_dict["channel_id"],
            message.chat.id,
            forward_ids,
        ):
            log.info("Query Repost: Successfully forwarded to channel.")
            repost_dict.update(
                {
                    "post_id": reposted[0].id,
                    "post_date": reposted[0].date.astimezone(tz.utc),
                }
            )
            with Session.begin() as session:
                session.add(Post(**repost_dict))
            log.info("Query Repost: Inserted Post: %s.", repost_dict)
            result = PostingResult.STATE_REPOSTED
            if data.reply:
                await send_reply_post(
                    update,
                    "reposted",
                    data.chan,
                    reposted[0].id,
                    link,
                )
            break
    # upload to cloud
    if (
        result == PostingResult.STATE_REPOSTED
        and art_link.type == LinkType.TWITTER
        and (art := await get_links(art_link))
    ):
        await upload_media(art._asdict(), update.effective_chat.id)
    return result


async def answer_query(update: Update, context: CallbackContext) -> None:
    notify(update, command="answer_query")
    # answer callback query
    await update.callback_query.answer()
    # get user data
    if not (data := await get_user_data(update)):
        await send_error(
            update,
            "You have no channel\\! Send /channel or /forward\\.",
        )
        log.error("Query: No data: <%d>.", update.effective_chat.id)
        return
    # check for forward mode
    if not data.forward:
        await send_error(
            update,
            "Forwarding mode is *off*\\! Turn it *on* to proceed\\.",
        )
        log.error("Query: Forwarding mode is turned off!")
        return
    match update.callback_query.data:
        case "repost":
            result = await answer_query_repost(update, context, data)
            # update text
            link, _, text = convert_entities_to_links(update)
            await update.effective_message.edit_text(
                f"~This [artwork]({esc(link)}) was already posted\\:"
                f" {text}~\\.\n\n{result_message[result]}",
                parse_mode=PM.MARKDOWN_V2,
            )
        case "post":
            result = await answer_query_post(update, context, data)
            # update text
            link, _, text = convert_entities_to_links(update)
            await update.effective_message.edit_text(
                f"~This [artwork]({esc(link)}) was already posted\\:"
                f" {text}~\\.\n\n{result_message[result]}",
                parse_mode=PM.MARKDOWN_V2,
            )
        case _:
            await send_error(update, "WTF\\?\\!")
            log.error("Query: This is impossible.")
