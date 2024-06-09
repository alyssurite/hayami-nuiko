"""Upload module"""
import logging
import os

from base64 import urlsafe_b64encode
from pathlib import Path

# parse json
import orjson

# upload dictionary, constants
from ..extra import UPLOAD_LINKS

# downloading media
from ..extra.download import download_media

# send requests
from ..extra.helpers import make_request, retry_request

# logger file handler
from ..extra.loggers import FILE_HANDLER

# get logger
log = logging.getLogger(__name__)


@retry_request
async def upload(
    file: bytes,
    name: str,
    link: str,
    kind: str = "file",
) -> bool:
    """Uploads file of certain type to Google Drive

    Args:
        file (bytes): file
        name: (str): filename
        link (str): link to upload to
        kind (str, optional): file type description. Defaults to "file".

    Returns:
        bool: did uploading succeed or not
    """
    if os.getenv("LOCAL"):
        log.info("Running in local mode, skipping...")
        return
    log.info("Uploading %s %r...", kind, name)
    params = {"name": name, "size": len(file)}
    if kind != "log file":
        response = await make_request(
            link,
            "POST",
            params=params,
            data=urlsafe_b64encode(b"\x00"),
            timeout=120,
        )
        info = orjson.loads(response.content)
        log.debug("JSON: %r.", info)
        if not info["ok"]:
            log.info("%s %r already exists.", kind.capitalize(), name)
            return False
    response = await make_request(
        link,
        "POST",
        params=params,
        data=urlsafe_b64encode(file),
        timeout=120,
    )
    info = orjson.loads(response.content)
    log.debug("JSON: %r.", info)
    if not info["ok"]:
        log.info("%s %r already exists.", kind.capitalize(), name)
        log.error("Something went wrong.")
        raise
    log.info("Done uploading %s %r.", kind, name)
    return True


async def upload_media(
    info: dict,
    user: int = 0,
    order: list[int] = None,
) -> None:
    """Uploads images to cloud

    Args:
        info (dict): art media dictionary
        user (int, optional): telegram user id. Defaults to 0.
        order (list[int], optional): which artworks to upload. Defaults to None.
    """
    if os.getenv("LOCAL"):
        log.info("Running in local mode, skipping...")
        return
    if user != UPLOAD_LINKS["user"] or info is None:
        return  # silently exit
    if not UPLOAD_LINKS["media"]:
        log.error("No media upload link.")
        return
    async for filename, file in download_media(info, order=order):
        suffix = filename.rsplit(".", 1)[1]
        kind = f"file ({suffix})"
        match suffix:
            case "mp4" | "octet-stream" | "mov" | "ismv":
                kind = "video"
            case "jpg" | "jpeg" | "jif" | "jfif" | "bmp" | "png" | "webp":
                kind = "image"
            case "gif":
                kind = "animated gif"
        await upload(
            file.read(),
            filename,
            UPLOAD_LINKS["media"],
            kind.lower(),
        )


async def upload_log() -> None:
    """Uploads log file to cloud"""
    if os.getenv("LOCAL"):
        log.info("Running in local mode, skipping...")
        return
    if not FILE_HANDLER:
        return  # silently exit
    if not UPLOAD_LINKS["log"]:
        log.error("No log upload link.")
        return
    with Path(FILE_HANDLER.baseFilename) as log_file:
        await upload(
            log_file.read_bytes(),
            log_file.name,
            UPLOAD_LINKS["log"],
            "log file",
        )
