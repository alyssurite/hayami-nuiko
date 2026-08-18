"""Twitter module"""

import dataclasses
import datetime
import os
import re

from typing import Optional

# download from any network now
import gallery_dl

# parse json
import orjson
import structlog

# json-serializable dataclasses
from dataclasses_json import dataclass_json

# parse datetime
from dateutil.parser import parse

# twitter api class
from gallery_dl.extractor.twitter import TwitterAPI

# link dictionary
from yaminui.api import LINKS

# import ArtWorkMedia
from yaminui.api.namedtuples import ArtWorkMedia, TweetContent

# escape markdown
from yaminui.bot import unescape_html

# fake headers
from yaminui.extra import FAKE_HEADERS

# get file size, send requests
from yaminui.extra.helpers import get_file_size, make_request

# env variables
from yaminui.extra.settings import bot_settings

# get logger
log = structlog.get_logger(__name__)

# twitter quality
QUALITY = ("orig", "large", "medium", "small")

# twitter dictionary
TWI = LINKS["twitter"]

# tweet URL
TWEET_URL = "https://twitter.com/web/status"


@dataclass_json
@dataclasses.dataclass
class TextLink:
    text: Optional[str]
    url: str
    tcourl: Optional[str]
    indices: tuple[int, int]


class Medium:
    pass


@dataclass_json
@dataclasses.dataclass
class Photo(Medium):
    previewUrl: str
    fullUrl: str
    kind: str = "Photo"
    altText: str = ""


@dataclass_json
@dataclasses.dataclass
class VideoVariant:
    url: str
    contentType: Optional[str]
    bitrate: Optional[int]


@dataclass_json
@dataclasses.dataclass
class Video(Medium):
    thumbnailUrl: str
    variants: list[VideoVariant]
    kind: str = "Video"
    duration: Optional[float] = None
    views: Optional[int] = None
    altText: str = ""


@dataclass_json
@dataclasses.dataclass
class Gif(Medium):
    thumbnailUrl: str
    variants: list[VideoVariant]
    kind: str = "Gif"
    altText: str = ""


@dataclass_json
@dataclasses.dataclass
class User:
    username: str
    id: int
    displayname: Optional[str] = None

    @property
    def url(self):
        return f"https://twitter.com/{self.username}"

    def __str__(self):
        return self.url


@dataclass_json
@dataclasses.dataclass
class Tweet:
    url: str
    date: datetime.datetime
    rawContent: str
    renderedContent: str
    id: int
    user: User
    replyCount: int
    retweetCount: int
    likeCount: int
    quoteCount: int
    conversationId: int
    lang: str
    links: Optional[list[TextLink]] = None
    media: Optional[list[Photo | Video | Gif]] = None
    quotedTweet: Optional["Tweet"] = None

    def __str__(self):
        return self.url

    def to_dict(self):
        data = dataclass_json.config().encoder(self)
        data["_type"] = "tweet"
        return data


# set config
gallery_dl.config.set(("extractor", "twitter"), "browser", "firefox:linux")
gallery_dl.config.set(("extractor", "twitter"), "csrf", "cookies")
gallery_dl.config.set(
    ("extractor", "twitter", "cookies"),
    "auth_token",
    bot_settings.tw_token,
)
gallery_dl.config.set(
    ("extractor", "twitter", "cookies"),
    "ct0",
    bot_settings.tw_cookie,
)


async def get_from_twimg_api(tweet_id: int) -> Optional[Tweet]:
    if response := await make_request(
        url="https://cdn.syndication.twimg.com/tweet-result",
        method="GET",
        headers={
            **FAKE_HEADERS,
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://platform.twitter.com",
            "Referer": "https://platform.twitter.com/",
        },
        params={
            "id": str(tweet_id),
            "lang": "en",
            "token": "ghostery",
        },
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        try:
            tweet_info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", tweet_info)
        if tomb := tweet_info.get("tombstone"):
            error = tomb["text"]["text"]
            if error.startswith("Age-restricted"):
                log.warning("Age-restricted content.")
            else:
                log.warning("Dead tweet.")
            return
        if not (user := tweet_info.get("user")):
            log.warning("Scraping failed.")
            return
        if not (media_info := tweet_info.get("mediaDetails")):
            log.warning("No media tweet.")
            return
        quote_info = None
        if quote := tweet_info.get("quoted_tweet", None):
            quote_info = Tweet(
                url=TWI["link"].format(
                    id=quote["id_str"],
                    author=quote["user"]["screen_name"],
                ),
                date=parse(quote["created_at"]),
                rawContent=quote["text"],
                renderedContent=quote["text"],
                id=quote["id_str"],
                user=None,
                replyCount=0,
                retweetCount=0,
                likeCount=0,
                quoteCount=0,
                conversationId=quote["id_str"],
                lang=quote["lang"],
            )
        return Tweet(
            url=TWI["link"].format(
                id=tweet_info["id_str"],
                author=user["screen_name"],
            ),
            date=parse(tweet_info["created_at"]),
            rawContent=tweet_info["text"],
            renderedContent=tweet_info["text"],
            id=tweet_info["id_str"],
            user=User(
                username=user["screen_name"],
                id=user["id_str"],
                displayname=user["name"],
            ),
            replyCount=0,
            retweetCount=0,
            likeCount=0,
            quoteCount=0,
            conversationId=tweet_info["id_str"],
            lang=tweet_info["lang"],
            links=[
                TextLink(
                    text=url["display_url"],
                    url=url["expanded_url"],
                    tcourl=url["url"],
                    indices=url["indices"],
                )
                for url in tweet_info["entities"]["urls"]
            ]
            or None,
            quotedTweet=quote_info,
            media=(
                [
                    (
                        Photo(
                            previewUrl=medium["media_url_https"],
                            fullUrl=medium["media_url_https"],
                        )
                        if medium["type"] == "photo"
                        else Video(
                            thumbnailUrl=medium["media_url_https"],
                            variants=[
                                VideoVariant(
                                    url=variant["url"],
                                    contentType=variant["content_type"],
                                    bitrate=variant.get("bitrate"),
                                )
                                for variant in medium["video_info"]["variants"]
                            ],
                            duration=(medium["video_info"].get("duration_millis") or 0)
                            / 1000,
                        )
                    )
                    for medium in media_info
                ]
                if media_info
                else None
            ),
        )


async def get_info_from_twitter_graphql(tweet_id: int) -> Optional[dict]:
    try:
        data_job = gallery_dl.job.DataJob(
            f"https://twitter.com/web/status/{tweet_id}",
            file=os.devnull,
        )
        data_job.extractor.api = TwitterAPI(data_job.extractor)
        if data := data_job.extractor.tweets():
            return data
        log.warning("Twitter GraphQL: No data.")
    except gallery_dl.exception.StopExtraction:
        log.warning("Twitter GraphQL: Invalid data.")
    except Exception as ex:
        log.warning("Twitter GraphQL: Excection occured: %s.", ex.args)
    return


async def get_from_twitter_api(tweet_id: int) -> Optional[Tweet]:
    """Gets tweet info from official twitter api by tweet id

    Args:
        tweet_id (int): tweet id

    Returns:
        Optional[Tweet]: tweet dictionary
    """
    if api_data := await get_info_from_twitter_graphql(tweet_id):
        data = api_data[0]
        if not (tweet_info := data.get("legacy", None)):
            log.warning("Scraping failed.")
            return
        if not (tweet_info["entities"].get("media", None)):
            log.warning("No media.")
            return
        quote_info = None
        quote = data.get("quoted_status_result", None)
        if quote and "tombstone" not in quote["result"]:
            qinfo = quote["result"]["legacy"]
            quote_info = Tweet(
                url=tweet_info["quoted_status_permalink"]["expanded"],
                date=parse(qinfo["created_at"]),
                rawContent=qinfo["full_text"],
                renderedContent=qinfo["full_text"],
                id=qinfo["id_str"],
                user=None,
                replyCount=qinfo["reply_count"],
                retweetCount=qinfo["retweet_count"],
                likeCount=qinfo["favorite_count"],
                quoteCount=qinfo["quote_count"],
                conversationId=qinfo["conversation_id_str"],
                lang=qinfo["lang"],
            )
        media_info = tweet_info["extended_entities"]["media"]
        user = data["core"]["user_results"]["result"]["legacy"]
        return Tweet(
            url=TWI["link"].format(
                id=tweet_info["id_str"],
                author=user["screen_name"],
            ),
            date=parse(tweet_info["created_at"]),
            rawContent=tweet_info["full_text"],
            renderedContent=tweet_info["full_text"],
            id=tweet_info["id_str"],
            user=User(
                username=user["screen_name"],
                id=tweet_info["user_id_str"],
                displayname=user["name"],
            ),
            replyCount=tweet_info["reply_count"],
            retweetCount=tweet_info["retweet_count"],
            likeCount=tweet_info["favorite_count"],
            quoteCount=tweet_info["quote_count"],
            conversationId=tweet_info["id_str"],
            lang=tweet_info["lang"],
            links=[
                TextLink(
                    text=url["display_url"],
                    url=url["expanded_url"],
                    tcourl=url["url"],
                    indices=url["indices"],
                )
                for url in tweet_info["entities"]["urls"]
            ]
            or None,
            quotedTweet=quote_info,
            media=(
                [
                    (
                        Photo(
                            previewUrl=medium["media_url_https"],
                            fullUrl=medium["media_url_https"],
                        )
                        if medium["type"] == "photo"
                        else Video(
                            thumbnailUrl=medium["media_url_https"],
                            variants=[
                                VideoVariant(
                                    url=variant["url"],
                                    contentType=variant["content_type"],
                                    bitrate=variant.get("bitrate"),
                                )
                                for variant in medium["video_info"]["variants"]
                            ],
                            duration=(medium["video_info"].get("duration_millis") or 0)
                            / 1000,
                        )
                    )
                    for medium in media_info
                ]
                if media_info
                else None
            ),
        )


async def process_twitter_medium(medium: Medium) -> Optional[TweetContent]:
    """Processes twitter medium

    Args:
        medium (Medium): medium to process

    Returns:
        Optional[TweetContent]: processed content
    """
    if isinstance(medium, Photo):
        if not (matched := re.search(TWI["file"], medium.fullUrl)):
            log.critical("Couldn't parse file: %s.", medium.fullUrl)
            return
        args = matched.groupdict()
        link = next(TWI["image"].format(**args, size=size) for size in QUALITY)
        return TweetContent(
            "photo",
            link,
            await get_file_size(link),
            medium.previewUrl,
        )
    elif isinstance(medium, Video) or isinstance(medium, Gif):
        link = next(
            animated.url
            for animated in sorted(
                medium.variants,
                key=lambda x: x.bitrate or 0,
                reverse=True,
            )
            if animated.contentType == "video/mp4" and (animated.bitrate or 0) < 50 << 20
        )
        return TweetContent(
            "video",
            link,
            await get_file_size(link),
            medium.thumbnailUrl,
        )
    else:
        log.critical("Unknown medium format: %s.", medium.__class__.__name__)
        return


async def get_twitter_media(media: list[Medium]) -> Optional[list[TweetContent]]:
    """Collects media links from tweet

    Args:
        media (list[Medium]): tweet media list

    Returns:
        Optional[list[TweetContent]]: tweet content list
    """
    content = []
    for medium in media:
        if not (item := await process_twitter_medium(medium)):
            return
        content.append(item)
    return content


async def process_tweet(tweet: Tweet) -> Optional[ArtWorkMedia]:
    """Processes tweet for media

    Args:
        tweet (Tweet): tweet dictionary

    Returns:
        Optional[ArtWorkMedia]: twitter media namedtuple
    """
    if not (content := await get_twitter_media(tweet.media)):
        log.warning("Exception occured: No links.")
        return
    text: str = tweet.rawContent
    # replace short links with full
    if tweet.links:
        for link in tweet.links:
            text = text.replace(link.tcourl, link.url)
    # remove media link from text
    text = re.sub(TWI["media"], "", text)
    # place other links after 2 new lines
    if tweet.quotedTweet and hasattr(tweet.quotedTweet, "url"):
        text = f"{text}\n\n{tweet.quotedTweet.url}"
    return ArtWorkMedia(
        LINKS["twitter"]["link"].format(id=tweet.id, author=tweet.user.username),
        LINKS["twitter"]["type"],
        int(tweet.id),
        tuple(item.type for item in content),
        int(tweet.user.id),
        tweet.user.displayname,
        tweet.user.username,
        tweet.date,
        "",
        await unescape_html(text.strip()),
        tuple(item.link for item in content),
        tuple(item.size for item in content),
        tuple(item.thumb for item in content),
    )


async def get_from_secret_api(tweet_id: int) -> Optional[Tweet]:
    """Gets tweet info from secret twitter api by tweet id

    Args:
        tweet_id (int): tweet id

    Returns:
        Optional[Tweet]: tweet dictionary
    """
    if response := await make_request(
        url=bot_settings.secret_api_url,
        params={
            "api_key": bot_settings.secret_api_key,
            "tweet_id": tweet_id,
        },
        timeout=60,
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        try:
            if not (tweet_info := orjson.loads(response.content)):
                log.warning("Failed to get tweet.")
                return
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", tweet_info)
        user_info, media_info, links_info, quote_info = (
            tweet_info.get("user"),
            tweet_info.get("media"),
            tweet_info.get("links"),
            tweet_info.get("quotedTweet"),
        )
        if not media_info:
            return
        media = []
        for medium in media_info:
            if not (kind := medium.get("kind")):
                continue
            if kind == "Photo":
                media.append(Photo(**medium))
            else:
                variants = []
                for variant in medium["variants"]:
                    variants.append(VideoVariant(**variant))
                medium["variants"] = variants
                media.append(Video(**medium))
        # process links
        links = []
        if links_info:
            for link in links_info:
                links.append(TextLink(**link))
        # process quote
        quote = None
        if quote_info:
            quoted_user = quote_info["user"]
            quote = Tweet(
                url=quote_info["url"],
                date=datetime.datetime.fromtimestamp(quote_info["date"]),
                rawContent=quote_info["rawContent"],
                renderedContent=quote_info["renderedContent"],
                id=quote_info["id"],
                replyCount=quote_info["replyCount"],
                retweetCount=quote_info["retweetCount"],
                likeCount=quote_info["likeCount"],
                quoteCount=quote_info["quoteCount"],
                conversationId=quote_info["conversationId"],
                lang=quote_info["lang"],
                user=User(
                    username=quoted_user["username"],
                    id=quoted_user["id"],
                    displayname=quoted_user["displayname"],
                ),
            )
        # return tweet
        return Tweet(
            url=tweet_info["url"],
            date=datetime.datetime.fromtimestamp(tweet_info["date"]),
            rawContent=tweet_info["rawContent"],
            renderedContent=tweet_info["renderedContent"],
            id=tweet_info["id"],
            replyCount=tweet_info["replyCount"],
            retweetCount=tweet_info["retweetCount"],
            likeCount=tweet_info["likeCount"],
            quoteCount=tweet_info["quoteCount"],
            conversationId=tweet_info["conversationId"],
            lang=tweet_info["lang"],
            links=links,
            user=User(
                username=user_info["username"],
                id=user_info["id"],
                displayname=user_info["displayname"],
            ),
            quotedTweet=quote,
            media=media,
        )


async def get_twitter_links(tweet_id: int | str) -> Optional[ArtWorkMedia]:
    """Gets twitter media links

    Args:
        tweet_id (int | str): tweet id

    Returns:
        Optional[ArtWorkMedia]: twitter media namedtuple
    """
    try:
        tweet_id = int(tweet_id)
    except ValueError:
        log.error("Invalid tweet id.")
        return
    try:
        for get_tweet in (
            get_from_secret_api,  # best
            get_from_twimg_api,  # from twitter
            get_from_twitter_api,  # great
        ):
            if tweet := await get_tweet(tweet_id):
                break
        else:
            log.error("No tweet.")
            return
    except Exception as ex:
        log.error(
            "Error %s: %r.",
            ex.__class__.__name__,
            ex,
            exc_info=True,
        )
        return
    if not tweet.media:
        log.error("No media.")
        return
    return await process_tweet(tweet)
