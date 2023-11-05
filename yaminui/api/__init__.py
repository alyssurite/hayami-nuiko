"""API module"""
from abc import ABC, abstractmethod


class AbstractStyle(ABC):
    """Abstract style class."""

    @classmethod
    @abstractmethod
    def next(cls, value: int) -> int:
        pass

    @classmethod
    @abstractmethod
    def validate(cls, value: int) -> bool:
        pass

    @classmethod
    @abstractmethod
    def get_style(cls, value: int) -> int:
        pass

    @classmethod
    @abstractmethod
    def get_example(cls, value: int) -> str:
        pass

    @classmethod
    @abstractmethod
    def get_format(
        cls,
        user: int,
        username: str,
        link: str,
        title: str = None,
        desc: str = None,
    ) -> str:
        pass


class BaseStyle(AbstractStyle):
    """Represents base style for other styles."""

    name = "Base"
    field = "base_style"
    styles = () = range(0)

    @classmethod
    def get_next_style(cls, value: int) -> int:
        return (value + 1) % len(cls.styles)

    @classmethod
    def validate(cls, value: int) -> bool:
        return value in cls.styles

    @classmethod
    def get_style(cls, value: int) -> int:
        return value % len(cls.styles)

    @classmethod
    def get_example(cls, value: int) -> str:
        return NotImplemented

    @classmethod
    def get_format(cls, **kwargs) -> str:
        return NotImplemented


# pixiv styles
class PixivStyle(BaseStyle):
    """Represents Pixiv style."""

    name = "Pixiv"
    field = "pixiv_style"
    styles = (
        IMAGE_LINK,
        IMAGE_INFO_LINK,
        IMAGE_INFO_EMBED_LINK,
        IMAGE_INFO_EMBED_LINK_DESC,
        INFO_LINK,
        INFO_EMBED_LINK,
    ) = range(6)

    @classmethod
    def get_example(cls, value: int) -> str:
        link = "https://www\\.pixiv\\.net/"
        match value:
            case PixivStyle.IMAGE_LINK:
                return "\\[ `Image(s)` \\]\n\nLink"
            case PixivStyle.IMAGE_INFO_LINK:
                return "\\[ `Image(s)` \\]\n\nTitle \\| Author\nLink"
            case PixivStyle.IMAGE_INFO_EMBED_LINK:
                return f"\\[ `Image(s)` \\]\n\n[Title \\| Author]({link})"
            case PixivStyle.IMAGE_INFO_EMBED_LINK_DESC:
                return (
                    f"\\[ `Image(s)` \\]\n\n[Author \\| @Username]({link})"
                    "\n\n*Title*\n\nDescription"
                )
            case PixivStyle.INFO_LINK:
                return "Artwork \\| Author\nLink"
            case PixivStyle.INFO_EMBED_LINK:
                return f"[Artwork \\| Author]({link})"
            case _:
                return "Unknown"

    @classmethod
    def get_format(
        cls,
        style: int,
        user: int,
        username: str,
        link: str,
        title: str = None,
        desc: str = None,
    ) -> str:
        match style:
            case PixivStyle.IMAGE_INFO_LINK:
                return f"{title} | {user}\n{link}"
            case PixivStyle.IMAGE_INFO_EMBED_LINK:
                return f"<a href='{link}'>{title} | {user}</a>"
            case PixivStyle.IMAGE_INFO_EMBED_LINK_DESC:
                return (
                    f"<a href='{link}'>{user} | @{username}</a>"
                    f"\n\n<b>{title}</b>"
                    f"\n\n{desc}"
                )
            case PixivStyle.INFO_LINK:
                return f"{title} | {user}\n{link}"
            case PixivStyle.INFO_EMBED_LINK:
                return f"<a href='{link}'>{title} | {user}</a>"
            case PixivStyle.IMAGE_LINK | _:
                return link


# twitter styles
class TwitterStyle(BaseStyle):
    """Represents Twitter style."""

    name = "Twitter"
    field = "twitter_style"
    styles = (
        LINK,
        IMAGE_LINK,
        IMAGE_LINK_DESC,
        IMAGE_INFO_EMBED_LINK,
        IMAGE_INFO_EMBED_LINK_DESC,
    ) = range(5)

    @classmethod
    def get_example(cls, value: int) -> str:
        link = "https://www\\.twitter\\.com/"
        match value:
            case TwitterStyle.LINK:
                return "Link"
            case TwitterStyle.IMAGE_LINK:
                return "\\[ `Image(s)` \\]\n\nLink"
            case TwitterStyle.IMAGE_LINK_DESC:
                return "\\[ `Image(s)` \\]\n\nLink\n\nDescription"
            case TwitterStyle.IMAGE_INFO_EMBED_LINK:
                return f"\\[ `Image(s)` \\]\n\n[Author \\| @Username]({link})"
            case TwitterStyle.IMAGE_INFO_EMBED_LINK_DESC:
                return (
                    f"\\[ `Image(s)` \\]\n\n[Author \\| @Username]({link})"
                    "\n\nDescription"
                )
            case _:
                return "Unknown"

    @classmethod
    def get_format(
        cls,
        style: int,
        user: int,
        username: str,
        link: str,
        title: str = None,
        desc: str = None,
    ) -> str:
        match style:
            case TwitterStyle.IMAGE_LINK_DESC:
                return f"{link}\n\n{desc}"
            case TwitterStyle.IMAGE_INFO_EMBED_LINK:
                return f"[{user} \\| @{username}]({link})"
            case TwitterStyle.IMAGE_INFO_EMBED_LINK_DESC:
                return f"[{user} \\| @{username}]({link})\n\n{desc}"
            case TwitterStyle.LINK | TwitterStyle.IMAGE_LINK | _:
                return link


# link types
class LinkType:
    types = (
        TWITTER,
        PIXIV,
    ) = range(2)

    @classmethod
    def validate(cls, value: int):
        return value in cls.types


# link dictionary
LINKS = {
    "twitter": {
        "re": r"""(?x)
            (?:
                (?:twitter|x)\.
                (?:com)\/
                (?P<author>.+?)\/
                (?:status(?:es)?\/)
            )
            (?P<id>\d+)
            (?:[&?]\w+\=\w+)*
            (?:
                (?:\s*\+\s*)
                (?P<illust>(?:\d{1,3}(?:-\d{1,3})?[\s\.\,\+]*)+)
            )?
        """,
        # example:
        # https://twitter.com/sandraghart/status/1693028247410184215?t=h5AFmBzg5wcGzshM-MOQGw&s=35+1
        # https://twitter.com/lsxh3/status/1522050328350318592+1+2
        "file": r"""(?x)
            (?:
                (?:
                    (?:media\/)|(?:\d+x\d+\/)|(?:tweet_video\/)
                )
                (?P<id>[^\.\?]+)
                (?:
                    (?:\?.*format\=)|(?:\.)
                )
            )
            (?P<format>\w+)
        """,
        "link": "https://twitter.com/{author}/status/{id}",
        "t.co": r"https:\/\/t\.co\/\w{10}$",
        "image": "https://pbs.twimg.com/media/{id}?format={format}&name={size}",
        "type": LinkType.TWITTER,
    },
    "pixiv": {
        "re": r"""(?x)
            (?:
                (?:pixiv\.net)\/
                (?:member_illust\.php\?(?:\w+\=\w+\&)*illust_id\=)
                |
                (?:(?:\w{2}\/)?artworks\/)
            )
            (?P<id>\d+)
            (?:
                (?:[&?]\w+\=\w+)*
                (?:\s*\+\s*)
                (?P<illust>(?:\d{1,3}(?:-\d{1,3})?[\s\.\,\+]*)+)
            )?
        """,
        "link": "https://www.pixiv.net/artworks/{id}",
        "type": LinkType.PIXIV,
    },
}
