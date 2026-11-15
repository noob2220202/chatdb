"""텔레그램 그룹 링크 해석. 네트워크 없이 문자열만 본다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from .models import LinkKind

_HOSTS = {"t.me", "telegram.me", "telegram.dog"}
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_HASH_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# t.me/<이것> 은 그룹이 아니라 기능 경로다.
_RESERVED = {
    "joinchat", "addstickers", "addemoji", "addtheme", "addlist", "share", "proxy", "socks",
    "setlanguage", "bg", "login", "iv", "confirmphone", "invoice", "boost", "giftcode", "m",
    "contact", "c", "s", "a", "k", "z", "auth", "nft", "stickers",
}  # fmt: skip


class LinkError(ValueError):
    """해석할 수 없는 링크. 메시지는 사용자에게 보여 줄 한국어 문장이다."""


@dataclass(frozen=True)
class LinkTarget:
    kind: LinkKind  # PUBLIC 또는 INVITE
    value: str
    """PUBLIC 이면 @ 없는 아이디, INVITE 면 초대 해시."""

    @property
    def dedupe_key(self) -> str:
        """같은 그룹을 가리키는지 비교할 때 쓰는 키."""
        if self.kind == LinkKind.PUBLIC:
            return f"public:{self.value.lower()}"
        return f"invite:{self.value}"

    @property
    def canonical_url(self) -> str:
        if self.kind == LinkKind.PUBLIC:
            return f"https://t.me/{self.value}"
        return f"https://t.me/+{self.value}"


def _public(name: str) -> LinkTarget:
    if not _USERNAME_RE.match(name):
        raise LinkError("그룹 아이디 형식이 올바르지 않아요.")
    if name.lower() in _RESERVED:
        raise LinkError("그룹 링크가 아니에요.")
    return LinkTarget(LinkKind.PUBLIC, name)


def _invite(value: str) -> LinkTarget:
    value = value.strip()
    if value.isdigit():
        raise LinkError("전화번호 링크로는 그룹에 가입할 수 없어요.")
    if not _HASH_RE.match(value):
        raise LinkError("초대 링크 형식이 올바르지 않아요.")
    return LinkTarget(LinkKind.INVITE, value)


def parse_link(raw: str) -> LinkTarget:
    """그룹 링크·아이디를 해석한다. 못 읽으면 LinkError.

    받는 형식:
      @name, name, t.me/name, https://t.me/name, t.me/name/123 (메시지 링크),
      t.me/+HASH, t.me/joinchat/HASH, tg://join?invite=HASH, tg://resolve?domain=name
    """
    text = raw.strip().strip("<>").strip()
    if not text:
        raise LinkError("링크가 비어 있어요.")
    if len(text) > 300:
        raise LinkError("링크가 너무 길어요.")

    if text.startswith("@"):
        return _public(text[1:])

    lowered = text.lower()
    if lowered.startswith("tg://"):
        parts = urlsplit(text)
        query = parse_qs(parts.query)
        action = (parts.netloc or parts.path.lstrip("/")).lower()
        if action == "join" and query.get("invite"):
            return _invite(query["invite"][0])
        if action == "resolve" and query.get("domain"):
            return _public(query["domain"][0])
        raise LinkError("지원하지 않는 tg:// 링크예요.")

    if "/" not in text and "." not in text:
        # 아이디만 적은 경우
        return _public(text)

    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _HOSTS:
        raise LinkError("텔레그램 링크(t.me)가 아니에요.")

    segments = [unquote(s) for s in parts.path.split("/") if s]
    if not segments:
        raise LinkError("그룹을 가리키는 링크가 아니에요.")

    first = segments[0]
    if first.startswith("+"):
        return _invite(first[1:])
    if first.startswith(" ") and first.strip():
        # 'https://t.me/ HASH' 처럼 + 가 공백으로 바뀐 경우
        return _invite(first.strip())
    key = first.lower()
    if key == "joinchat":
        if len(segments) < 2:
            raise LinkError("초대 링크가 잘렸어요.")
        return _invite(segments[1])
    if key == "c":
        raise LinkError("비공개 그룹의 메시지 링크로는 가입할 수 없어요. 초대 링크를 넣어 주세요.")
    if key == "addlist":
        raise LinkError("폴더 링크는 지원하지 않아요. 그룹 링크를 하나씩 넣어 주세요.")
    if key == "s" and len(segments) >= 2:
        return _public(segments[1])
    return _public(first)
