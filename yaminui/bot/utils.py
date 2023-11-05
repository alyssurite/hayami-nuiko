"""Utils module"""
import logging
import re

# telegram core bot api
from telegram import Update

# link types & link dictionary
from ..api import LINKS, LinkType

# namedtuples
from ..api.namedtuples import ArtWorkMedia, Link

# pixiv api
from ..api.pixiv import get_pixiv_links

# twitter api
from ..api.twitter import get_twitter_links

# bot constants
from ..bot import tg_post_link, tw_regex

# get logger
log = logging.getLogger(__name__)


def cid_to_channel_id(cid: int) -> int:
    return -(cid + 10**12)


def channel_id_to_cid(channel_id: int) -> int:
    return -(channel_id + 10**12)


def get_post_link(channel_id: int, post_id: int) -> str:
    """Assembles channel internal id and post id into internal telegram link.

    Args:
        channel_id (int): channel internal id.
        post_id (int): post id.

    Returns:
        str: internal telegram link.
    """
    return tg_post_link.format(cid=channel_id_to_cid(channel_id), post_id=post_id)


async def get_links(media: Link) -> ArtWorkMedia:
    if media.type == LinkType.TWITTER:
        return await get_twitter_links(media.id)
    if media.type == LinkType.PIXIV:
        return await get_pixiv_links(media.id)
    log.warning("Error: Unknown media type: %s.", media.type)
    return


async def extract_media_ids(art: dict) -> list[str]:
    match art["type"]:
        case LinkType.TWITTER:
            return [re.search(tw_regex, link)["id"] for link in art["links"]]
        case LinkType.PIXIV:
            return [str(art["id"])]
        case _:
            return


async def formatter(query: str) -> list[Link]:
    """Exctracts and formats links in text

    Args:
        query (str): text

    Returns:
        list[Link]: list of Links
    """
    if not query:
        return []
    links = []
    for re_key, re_type in LINKS.items():
        for url in re.finditer(re_type["re"], query):
            # dictionary keys = format args
            link = re_type["link"].format(**url.groupdict())
            log.info("Formatter: Received %s link: %r.", re_key, link)
            links.append(
                Link(
                    re_type["type"],
                    link,
                    int(url["id"]),
                    url["illust"] if url.lastgroup == "illust" else None,
                )
            )
    return links


async def check_message_media(update: Update):
    return bool(
        update.effective_message.animation
        or update.effective_message.document
        or update.effective_message.photo
        or update.effective_message.video
    )


async def get_text(update: Update):
    return "|".join(
        text
        for text in [
            entity.url
            for entity in update.effective_message.entities
            + update.effective_message.caption_entities
        ]
        + [
            update.effective_message.text,
            update.effective_message.caption,
        ]
        if text
    )
