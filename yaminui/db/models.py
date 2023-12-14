"""Database models module"""

from datetime import datetime
from typing import Annotated, List, Optional

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship, validates

# import pixiv & twitter styles and link types
from ..api import LinkType, PixivStyle, TwitterStyle

# get declarative base class
from . import Base

bool0 = Annotated[bool, mapped_column(default=False)]
bool1 = Annotated[bool, mapped_column(default=True)]


class Channel(Base):
    """Table for storing telegram channel data"""

    __tablename__ = "channel"
    # channel public id
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    @validates("id")
    def _write_once_id(self, key: str, value: int) -> int:
        """Allows only 1 write to the field

        Args:
            key (str): field name
            value (int): field value

        Raises:
            ValueError: attempt to change or wrong value

        Returns:
            int: new field value
        """
        if self.id:
            raise ValueError(f"Field {key!r} is write-once.")
        elif not value < 0:
            raise ValueError(f"Field {key!r} can't be positive number.")
        return value

    # channel internal id
    cid: Mapped[int] = column_property(-(id + 10**12))

    @validates("cid")
    def _read_only_cid(self, key: str):
        """Allows only reads for cid fiels

        Args:
            key (str): field name

        Raises:
            ValueError: attempt to change
        """
        raise ValueError(f"Field {key!r} is read-only.")

    # channel name
    name: Mapped[Optional[str]]
    # channel link
    link: Mapped[Optional[str]]
    # if bot is admin
    is_admin: Mapped[bool0]

    # RL: 1-1 Admin with Channels
    admin: Mapped[Optional["User"]] = relationship(back_populates="channel")
    # FK: admin user
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("user.id"))

    # RL: 1-M Channnel posts
    posts: Mapped[List["Post"]] = relationship(
        back_populates="channel",
        foreign_keys="Post.channel_id",
    )

    # RL: 1-M Channnel reposts
    reposts: Mapped[List["Post"]] = relationship(
        back_populates="forwarded_channel",
        foreign_keys="Post.forwarded_channel_id",
    )

    # if channel was deleted
    is_deleted: Mapped[bool0]


class User(Base):
    """Table for storing telegram user data"""

    __tablename__ = "user"
    # telegram account id
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    @validates("id")
    def _write_id_once(self, key: str, value: int) -> int:
        """Allows only 1 write to the field

        Args:
            key (str): field name
            value (int): field value

        Raises:
            ValueError: attempt to change

        Returns:
            int: new field value
        """
        if getattr(self, key):
            raise ValueError(f"Field {key!r} is write-once.")
        return value

    # full name = first name + last name
    full_name: Mapped[Optional[str]]
    # nick name if available
    nick_name: Mapped[Optional[str]]

    # RL: 1-1 Admin with Channel
    channel: Mapped[Optional["Channel"]] = relationship("Channel", back_populates="admin")

    # enable posting video and gifs
    media_mode: Mapped[bool0]
    # enable replying to sent links?
    reply_mode: Mapped[bool1]
    # enable forwarding to channel?
    forward_mode: Mapped[bool0]

    @validates("forward_mode")
    def validate_forwarding(self, key: str, value: bool) -> bool:
        """Allows to change forwarding to True only if channel is present

        Args:
            key (str): field name
            value (bool): field value

        Raises:
            ValueError: attempt to break condition

        Returns:
            bool: new field value
        """
        if value and not self.channel:
            raise ValueError(f"Field 'channel' is empty. Can't update {key!r}.")
        return value

    # pixiv style
    pixiv_style: Mapped[int] = mapped_column(default=3)

    @validates("pixiv_style")
    def validate_pixiv_style(self, key: str, value: int) -> int:
        """Validates pixiv style

        Args:
            key (str): field name
            value (int): field value

        Raises:
            ValueError: attempt to set incorrect value

        Returns:
            int: new field value
        """
        if PixivStyle.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # twitter style
    twitter_style: Mapped[int] = mapped_column(default=4)

    @validates("twitter_style")
    def validate_twitter_style(self, key: str, value: int):
        """Validates twitter style

        Args:
            key (str): field name
            value (int): field value

        Raises:
            ValueError: attempt to set incorrect value

        Returns:
            int: new field value
        """
        if TwitterStyle.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # all info about the last link, depending on the type
    last_info: Mapped[Optional[dict]] = mapped_column(JSON)
    # in case if user should be banned
    is_banned: Mapped[bool0]
    # if user was deleted
    is_deleted: Mapped[bool0]
    # user api token
    token: Mapped[Optional[str]] = mapped_column(String(32))


class Post(Base):
    """Table for storing channel post data"""

    __tablename__ = "post"
    # post record id
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )

    # FK: artwork that post contains
    artwork_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("artwork.id"))
    # RL: M-1 Posts with Artwork
    artwork: Mapped["ArtWork"] = relationship(
        back_populates="posts", foreign_keys=[artwork_id]
    )

    # FK: channel that post is from
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("channel.id"),
    )
    # RL: M-1 Posts in Channel
    channel: Mapped["Channel"] = relationship(
        back_populates="posts",
        foreign_keys=[channel_id],
    )

    # channel post id
    post_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # post datetime
    post_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # is this post original or not?
    is_original: Mapped[bool1]
    # is this post forwarded or not?
    is_forwarded: Mapped[bool0]

    # FK: channel that post is forwarded from
    forwarded_channel_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("channel.id"),
    )
    # RL: M-1 Forwarded Posts from Channel
    forwarded_channel: Mapped[Optional["Channel"]] = relationship(
        back_populates="reposts",
        foreign_keys=[forwarded_channel_id],
    )

    # add unique constraints
    __table_args__ = (
        # no double posts
        UniqueConstraint("channel_id", "post_id", name="uix_post"),
    )


class ArtWork(Base):
    """Table for storing artwork data"""

    __tablename__ = "artwork"
    # artwork record id
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )

    # artwork id
    aid: Mapped[int] = mapped_column(BigInteger, index=True)

    # twitter or pixiv?
    type: Mapped[int]

    @validates("type")
    def validate_type(self, key: str, value: int):
        """Validates link style

        Args:
            key (str): field name
            value (int): field value

        Raises:
            ValueError: attempt to set incorrect value

        Returns:
            int: new field value
        """
        if LinkType.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # RL: 1-M Channnel posts
    posts: Mapped[List["Post"]] = relationship(
        back_populates="artwork",
        foreign_keys="Post.artwork_id",
    )

    # files
    files: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String, dimensions=1))

    # add unique constraints
    __table_args__ = (
        # ideally:
        UniqueConstraint("type", "aid", name="uix_artwork"),
    )
