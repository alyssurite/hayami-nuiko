"""Download module"""

import re
import tempfile

from typing import AsyncGenerator

# file extension check
import magic
import structlog

# link types
from yaminui.api import LinkType

# fake headers
from yaminui.extra import FAKE_HEADERS, PIXIV_HEADERS, UPLOAD_LINKS

# make request
from yaminui.extra.helpers import file_request, make_request

# get logger
log = structlog.get_logger(__name__)

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
        return tuple(info["links"][index - 1] for index in order)
    # else download only 10 first files
    if len(info["links"]) > 10:
        return tuple(info["links"][:10])
    # else no special rules apply
    return tuple(info["links"])


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
        item_idx = order[idx] - 1 if order else idx
        media = await make_request(link, "GET", headers=headers)
        filename = await get_filename(link, media.content[:1024])
        log.debug("Filename: %r.", filename)
        with tempfile.TemporaryFile() as file:
            file.write(media.content)
            if not full and (
                info["type"] == LinkType.PIXIV
                and info["media"] in ("illust", "manga")
                or info["type"] == LinkType.TWITTER
                and info["media"][item_idx] == "photo"
            ):
                try:
                    file.seek(0)
                    image = await file_request(
                        UPLOAD_LINKS["resizer"],
                        "POST",
                        timeout=120,
                        params={"to_ext": "jpeg"},
                        files={"upload_file": file.read()},
                    )
                    # validate resizer actually returned a JPEG (magic bytes \xff\xd8\xff)
                    if image[:3] == b"\xff\xd8\xff":
                        file.seek(0)
                        file.truncate()
                        file.write(image)
                        # resizer always returns JPEG — update filename to match
                        filename = re.sub(r"\.[a-z]{2,4}$", ".jpeg", filename)
                    else:
                        log.warning(
                            "Resizer returned non-JPEG data (%d bytes, starts %r), "
                            "using original content.",
                            len(image),
                            image[:16],
                        )
                except Exception as exc:
                    log.warning("Resizer failed (%r), using original content.", exc)
            file.seek(0)
            yield (filename, file)
