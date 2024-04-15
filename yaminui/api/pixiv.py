"""Pixiv module"""
import logging
import os

from typing import Optional

# parse json
import orjson

# pixiv api
from pixivpy_async import AppPixivAPI, PixivClient

# fake headers
from ..extra import FAKE_HEADERS

# send requests
from ..extra.helpers import make_request, retry_request

# link types, link dictionary
from . import LINKS, LinkType

# ArtWorkMedia
from .namedtuples import ArtWorkMedia

# pixiv tokens
pixiv_api = {
    "ACCESS_TOKEN": os.environ["PX_ACCESS"],
    "REFRESH_TOKEN": os.environ["PX_REFRESH"],
}

# get logger
log = logging.getLogger(__name__)


async def get_pixiv_media(illust: dict) -> ArtWorkMedia:
    """Collects information about pixiv artwork

    Args:
        illust (dict): dictionary of illustration.

    Returns:
        ArtWorkMedia: artwork namedtuple.
    """
    if illust.type == "ugoira":
        if not (
            response := await make_request(
                "https://ugoira.huggy.moe/api/illusts/queue",
                headers={**FAKE_HEADERS, "Content-Type": "application/json"},
                data=orjson.dumps({"text": str(illust.id)}),
            )
        ):
            return
        try:
            if not (ugoira := orjson.loads(response.content))["ok"]:
                return
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        else:
            links = (
                (ugoira["data"][0]["preview"]["mp4"],),
                (illust.image_urls.large,),
            )
    elif illust.meta_single_page:
        links = (
            (illust.meta_single_page.original_image_url,),
            (illust.image_urls.large,),
        )
    elif illust.type not in ("ugoira", "novel"):
        links = (
            tuple(page.image_urls.original for page in illust.meta_pages),
            tuple(page.image_urls.large for page in illust.meta_pages),
        )
    return ArtWorkMedia(
        LINKS["pixiv"]["link"].format(id=illust.id),
        LinkType.PIXIV,
        illust.id,
        illust.type,  # 'ugoira' or 'illust'
        illust.user.id,
        illust.user.name,
        illust.user.account,
        illust.create_date,
        illust.title,
        illust.caption,
        links[0],
        [0 for _ in links[0]],
        links[1],
    )


@retry_request
async def get_pixiv_info(pixiv_id: int) -> ArtWorkMedia:
    """Gets illustration info with pixiv API by illustration id

    Args:
        pixiv_id (int): pixiv illustration id.

    Returns:
        ArtWorkMedia: artwork namedtuple.
    """
    async with PixivClient() as client:
        aapi = AppPixivAPI(client=client)
        await aapi.login(refresh_token=os.environ["PX_REFRESH"])
        # Doing stuff...
        log.debug("Trying to fetch artwork...")
        json_result = await aapi.illust_detail(pixiv_id)
        if json_result.error:
            log.warning("This artwork was probably deleted.")
            return
        if not json_result.illust.visible:
            log.warning("This artwork is not public.")
            return
        log.debug("Response: %r.", json_result.illust)
        return json_result.illust


async def get_pixiv_links(pixiv_id: int) -> Optional[ArtWorkMedia]:
    """Gets pixiv illustration info with pixiv API by illustration id

    Args:
        pixiv_id (int): pixiv illustration id.

    Returns:
        Optional[ArtWorkMedia]: artwork namedtuple.
    """
    if info := await get_pixiv_info(pixiv_id):
        return await get_pixiv_media(info)
    log.error("No illustration info found.")
    return
