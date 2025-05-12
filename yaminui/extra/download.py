"""Download module"""

import logging
import re
import tempfile

from typing import AsyncGenerator

# file extension check
import magic

# working with images
from PIL import Image

# link types
from ..api import LinkType

# fake headers
from ..extra import FAKE_HEADERS, PIXIV_HEADERS, UPLOAD_LINKS

# make request
from ..extra.helpers import file_request, make_request

# get logger
log = logging.getLogger(__name__)

# max image side length
IM_MAX = (2560, 2560)

# shrinked max image side length
IM_SHR = (2240, 2240)

# filename pattern
file_pattern = r"""(?x)
    (?:
        ^
        (?:.*)\/
        (?P<name>.*?)
        (?:
            (?:\?.*format\=)|(?:\.)
        )
        (?P<format>[a-z]{2,4})
        (?:.*)
        $
    )
"""


async def get_filename(link: str, media: bytes) -> str:
    if not (reg := re.search(file_pattern, link)):
        log.warning("Couldn't get name or format: %s.", link)
        return link.rsplit("/")[1]
    ext = magic.from_buffer(media, mime=True).split("/")[1]
    if ext == "octet-stream":
        ext = "mp4"
    return f'{reg["name"]}.{ext}'


async def get_links(
    info: dict,
    *,
    full: bool = True,
    order: tuple[int] = None,
) -> tuple[str]:
    """Gets appropriate tuple of links for current info

    Args:
        info (dict): art media info.
        full (bool, optional): full size or not. Defaults to True.
        order (tuple[int], optional): order of artworks. Defaults to None.

    Returns:
        tuple[str]: tuple of links
    """
    # download in order if present
    if order:
        return (info["links"][index - 1] for index in order)
    # else download only 10 first files
    if len(info["links"]) > 10:
        info["links"][:10]
    # else no special rules apply
    return info["links"]


async def download_media(
    info: dict,
    *,
    full: bool = True,
    order: tuple[int] = None,
) -> AsyncGenerator[tuple[str, tempfile._TemporaryFileWrapper], None]:
    """Downloads files using art media dictionary depending on order list and
    yields downloaded content in full size or resized to current max size

    Args:
        info (dict): art media dictionary
        full (bool, optional): full size or not. Defaults to True.
        order (tuple[int], optional): order of artworks. Defaults to None.

    Yields:
        AsyncGenerator[tuple[str, tempfile._TemporaryFileWrapper], None]:
        generator of filenames and downloaded content as temporary files
    """
    if not info:
        log.error("No info supplied.")
        yield
    headers = PIXIV_HEADERS if info["type"] == LinkType.PIXIV else FAKE_HEADERS
    idx = -1
    for link in await get_links(info, full=full, order=order):
        idx += 1
        media = await make_request(link, "GET", headers=headers)
        filename = await get_filename(link, media.content[:1024])
        log.debug("Filename: %r.", filename)
        with tempfile.TemporaryFile() as file:
            file.write(media.content)
            if not full and (
                info["type"] == LinkType.PIXIV
                and info["media"] in ("illust", "manga")
                or info["type"] == LinkType.TWITTER
                and info["media"][idx] == "photo"
            ):
                with Image.open(file) as im:
                    log.debug("Original size: %d x %d.", *im.size)
                    log.debug("Size sum in pixels: %d.", sum(im.size))
                    log.debug("Image size in bytes: %d.", file.seek(0, 2))
                    # check if its width + height > 10000 or its size > 10 MB
                    if sum(im.size) > 10000 or file.tell() > 10 << 20:
                        file.seek(0)
                        image = await file_request(
                            UPLOAD_LINKS["resizer"],
                            "POST",
                            timeout=120,
                            files={"upload_file": file.read()},
                        )
                        file.seek(0)
                        file.truncate()
                        file.write(image)
            file.seek(0)
            yield (filename, file)
