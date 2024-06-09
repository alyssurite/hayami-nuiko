"""Namedtuples module"""
from collections import namedtuple

# main namedtuple for any links
Link = namedtuple(
    "Link",
    [
        "type",
        "link",
        "id",
        "illust",
        "above",
    ],
)

# twitter media content
TweetContent = namedtuple(
    "TweetContent",
    (
        "type",
        "link",
        "size",
        "thumb",
    ),
)

# main namedtuple for artwork info
ArtWorkMedia = namedtuple(
    "ArtWorkMedia",
    [
        "link",
        "type",
        "id",
        "media",
        "user_id",
        "user",
        "username",
        "date",
        "title",
        "desc",
        "links",
        "sizes",
        "thumbs",
    ],
)
