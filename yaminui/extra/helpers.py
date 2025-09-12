"""Helpers module"""

import logging

from typing import Any

# send requests
import httpx

# hardcore retrying
from tenacity import AsyncRetrying, before_sleep_log, stop_after_attempt, wait_fixed

# fake headers
from yaminui.extra import FAKE_HEADERS, RETRY_MAX_TIMEOUT, RETRY_MAX_TRIES

# get logger
log = logging.getLogger(__name__)


def retry_request(func):
    """Decorator that retries telegram send function

    Args:
        func (Callable): telegram send function
    """
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(RETRY_MAX_TRIES),
        wait=wait_fixed(RETRY_MAX_TIMEOUT),
        before_sleep=before_sleep_log(log, log_level=logging.WARNING),
    ).wraps(func)


@retry_request
async def file_request(url: str, method: str = "POST", **kwargs) -> bytes:
    response = await make_request(url, method, **kwargs)
    if response.is_success and (file := response.content):
        return file
    else:
        raise Exception("No file content was received.")


@retry_request
async def make_request(
    url: str,
    method: str = "POST",
    *,
    headers: dict = None,
    follow_redirects: bool = True,
    timeout: int = 10,
    **kwargs: Any,
) -> httpx.Response:
    """Makes request with httpx.Session

    Args:
        url (str): request url
        method (str, optional): request method. Defaults to "POST".
        headers (dict, optional): request headers. Defaults to None.
        follow_redirects (bool, optional): follow redirecting. Defaults to True.
        timeout (int, optional): request timeout. Defaults to 10.

    Returns:
        httpx.Response: response
    """
    async with httpx.AsyncClient() as client:
        if not headers:
            headers = FAKE_HEADERS.copy()

        return await client.request(
            method=method,
            url=url,
            headers=headers,
            follow_redirects=follow_redirects,
            timeout=timeout,
            **kwargs,
        )


async def get_file_size(link: str, headers: dict = FAKE_HEADERS) -> int:
    """Gets file size

    Args:
        link (str): downloadable file.
        headers (dict): request headers to use. Defaults to FAKE_HEADERS.

    Returns:
        int: size of file
    """
    if link:
        response = await make_request(link, "HEAD", headers=headers)
        if response.is_success and (size := response.headers.get("Content-Length", 0)):
            return int(size)
    return 0
