"""Upload module"""

import asyncio

from base64 import urlsafe_b64encode
from pathlib import Path

# parse json
import orjson
import structlog

# parse HTML error pages gracefully
from bs4 import BeautifulSoup

# upload dictionary, constants
from yaminui.extra import UPLOAD_LINKS

# downloading media
from yaminui.extra.download import download_media

# send requests
from yaminui.extra.helpers import make_request, retry_request

# logger file handler
from yaminui.extra.loggers import FILE_HANDLER

# env variables
from yaminui.extra.settings import bot_settings

# get logger
log = structlog.get_logger(__name__)

# Concurrency lock to prevent Google Apps Script connection thrashing
SCRIPT_SEMAPHORE = asyncio.Semaphore(4)


def _parse_json_response(response, action_desc: str) -> dict:
    """Safely parses JSON response.

    If Google returns an HTML error page (e.g. rate limit / 503 / 429), BeautifulSoup
    extracts the message cleanly so it can be retried by @retry_request.
    """
    try:
        return orjson.loads(response.content)
    except orjson.JSONDecodeError as err:
        status_code = getattr(response, "status_code", "N/A")
        raw_content = response.content.decode("utf-8", errors="replace")

        # Parse HTML response using BeautifulSoup
        extracted_msg = ""
        try:
            soup = BeautifulSoup(raw_content, "html.parser")
            error_el = (
                soup.find(class_="errorMessage") or soup.find("p") or soup.find("title")
            )
            if error_el:
                extracted_msg = error_el.get_text(strip=True)
        except Exception:
            pass

        clean_detail = extracted_msg or raw_content[:120].replace("\n", " ")

        log.error(
            "Google Apps Script returned non-JSON response",
            action=action_desc,
            status_code=status_code,
            error_detail=clean_detail,
        )
        raise RuntimeError(
            f"Server returned non-JSON response during {action_desc} "
            f"[HTTP {status_code}]: {clean_detail}"
        ) from err


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
        name (str): filename
        link (str): link to upload to
        kind (str, optional): file type description. Defaults to "file".

    Returns:
        bool: did uploading succeed or not
    """
    if bot_settings.local_mode:
        log.info("Running in local mode, skipping...")
        return False

    log.info("Uploading %s %r...", kind, name)
    file_size = len(file)
    params = {"name": name, "size": file_size}

    async with SCRIPT_SEMAPHORE:
        # Step 1: Probe file existence via lightweight 'check' action
        if kind != "log file":
            check_params = {**params, "action": "check"}
            response = await make_request(
                link,
                "POST",
                params=check_params,
                follow_redirects=True,
                timeout=30,
            )
            info = _parse_json_response(response, f"check probe for '{name}'")
            log.debug("Check JSON: %r", info)

            if not info.get("ok"):
                error_msg = info.get("error", "Unknown check error")
                log.error("Check probe failed for %s %r: %s", kind, name, error_msg)
                raise RuntimeError(f"Google Drive check failed: {error_msg}")

            if info.get("exists"):
                log.info("%s %r already exists on Drive.", kind.capitalize(), name)
                return False

        # Step 2: Perform full upload
        upload_params = {**params, "action": "upload"}
        response = await make_request(
            link,
            "POST",
            params=upload_params,
            data=urlsafe_b64encode(file),
            follow_redirects=True,
            timeout=120,
        )
        info = _parse_json_response(response, f"upload for '{name}'")
        log.debug("Upload JSON: %r", info)

        if not info.get("ok"):
            error_msg = info.get("error", "Unknown upload error")
            log.error("Upload failed for %s %r: %s", kind, name, error_msg)
            raise RuntimeError(f"Google Drive upload failed: {error_msg}")

        if info.get("exists"):
            log.info("%s %r already exists on Drive (skipped).", kind.capitalize(), name)
            return False

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
    if bot_settings.local_mode:
        log.info("Running in local mode, skipping...")
        return
    if user != UPLOAD_LINKS.get("user") or not info:
        return

    if not UPLOAD_LINKS.get("media"):
        log.error("No media upload link configured.")
        return

    # Suffix mapping for kind description
    video_exts = {"mp4", "octet-stream", "mov", "ismv"}
    image_exts = {"jpg", "jpeg", "jif", "jfif", "bmp", "png", "webp"}

    async for filename, file in download_media(info, order=order):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in video_exts:
            kind = "video"
        elif ext in image_exts:
            kind = "image"
        elif ext == "gif":
            kind = "animated gif"
        else:
            kind = f"file ({ext})" if ext else "file"

        # If file is a file-like object, read bytes, otherwise use directly
        file_bytes = file.read() if hasattr(file, "read") else file

        await upload(
            file_bytes,
            filename,
            UPLOAD_LINKS["media"],
            kind,
        )


async def upload_log() -> None:
    """Uploads log file to cloud"""
    if bot_settings.local_mode:
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
