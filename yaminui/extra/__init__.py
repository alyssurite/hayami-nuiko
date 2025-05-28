"""Extra module"""

import os

# working with env
from dotenv import load_dotenv

# load .env file
load_dotenv()

# upload dictionary
UPLOAD_LINKS = {
    "user": int(os.getenv("USER_ID") or 0),
    "media": os.getenv("GD_MEDIA"),
    "log": os.getenv("GD_LOG"),
    "resizer": os.getenv("RESIZER_API"),
}

# constants for trying
RETRY_MAX_TRIES, RETRY_MAX_TIMEOUT = 3, 5

# request headers
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0",
    "Accept-Language": "en-US,en;q=0.5",
}

FAKE_HEADERS = {
    **BASE_HEADERS,
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

PIXIV_HEADERS = {
    "user-agent": "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)",
    "app-os-version": "14.6",
    "app-os": "ios",
    "referer": "https://www.pixiv.net/",
    "referrer-policy": "strict-origin-when-cross-origin",
}
