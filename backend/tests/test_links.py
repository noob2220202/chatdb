"""그룹 링크 해석 테스트."""

from __future__ import annotations

import pytest

from app.links import LinkError, LinkTarget, parse_link
from app.models import LinkKind

HASH = "AbCdEf_-123456"


# ---------------------------------------------------------------------------
# 공개 그룹 (아이디)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "@durov",
        "durov",
        "t.me/durov",
        "https://t.me/durov",
        "http://t.me/durov",
        "https://t.me/durov/",
        "t.me/durov/123",  # 메시지 링크
        "https://t.me/durov/123?single",
        "https://t.me/durov/123/456",  # 주제 안의 메시지 링크
        "https://t.me/durov?start=abc",
        "t.me/durov?ref=https://example.com",  # 쿼리 안의 :// 를 스킴으로 보지 않는다
        "https://t.me/durov#comments",
        "https://www.t.me/durov",
        "https://telegram.me/durov",
        "telegram.dog/durov",
        "t.me/s/durov",  # 웹 미리보기
        "https://t.me/s/durov/55",
        "tg://resolve?domain=durov",
        "tg://resolve?domain=durov&post=12",
        "TG://RESOLVE?domain=durov",
        "<https://t.me/durov>",
        "  https://t.me/durov  \n",
    ],
)
def test_public_forms(raw: str) -> None:
    assert parse_link(raw) == LinkTarget(LinkKind.PUBLIC, "durov")


def test_public_name_keeps_case_but_dedupes_case_insensitively() -> None:
    target = parse_link("HTTPS://T.ME/Seoul_Market")

    assert target == LinkTarget(LinkKind.PUBLIC, "Seoul_Market")
    assert target.canonical_url == "https://t.me/Seoul_Market"
    assert target.dedupe_key == "public:seoul_market"
    assert target.dedupe_key == parse_link("@seoul_market").dedupe_key


@pytest.mark.parametrize("name", ["abcd", "a_b_c", "abcd_", "a" * 32, "Room2026"])
def test_public_name_bounds(name: str) -> None:
    assert parse_link(f"@{name}").value == name


@pytest.mark.parametrize(
    "raw",
    [
        "@",
        "@abc",  # 너무 짧음
        "@" + "a" * 33,  # 너무 김
        "@1abcd",  # 숫자로 시작
        "@_abcd",  # 밑줄로 시작
        "@with-dash",
        "@@durov",
        "한글아이디",
        "t.me/@durov",
        "https://t.me/durov extra",
        "https://t.me/s",
        "?",
        "#",
        "+",
        "\x00",
        "https://t.me/%",
        "tg://resolve?domain=ab",
        "tg://resolve?domain=durov%20x",
    ],
)
def test_bad_public_name(raw: str) -> None:
    with pytest.raises(LinkError, match="그룹 아이디 형식이 올바르지 않아요"):
        parse_link(raw)


@pytest.mark.parametrize("raw", ["t.me/durov%0A", "tg://resolve?domain=durov%0A"])
def test_encoded_newline_is_not_accepted_as_part_of_the_name(raw: str) -> None:
    with pytest.raises(LinkError):
        parse_link(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "@joinchat",
        "t.me/share/url?url=https://example.com",
        "t.me/addstickers/SomePack",
        "t.me/proxy?server=1.2.3.4",
        "t.me/boost/durov",
        "https://t.me/login",
    ],
)
def test_feature_paths_are_not_groups(raw: str) -> None:
    with pytest.raises(LinkError, match="그룹 링크가 아니에요"):
        parse_link(raw)


# ---------------------------------------------------------------------------
# 초대 링크
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        f"t.me/+{HASH}",
        f"https://t.me/+{HASH}",
        f"https://t.me/+{HASH}?utm=1",
        f"https://t.me/%2B{HASH}",
        f"https://t.me/ {HASH}",  # + 가 공백으로 바뀐 채 붙여 넣은 경우
        f"https://t.me/joinchat/{HASH}",
        f"t.me/joinchat/{HASH}/",
        f"t.me/JoinChat/{HASH}",
        f"https://telegram.me/joinchat/{HASH}",
        f"tg://join?invite={HASH}",
        f"TG://JOIN?invite={HASH}",
        f"<https://t.me/+{HASH}>",
        f"https://t.me/+{HASH}\n",
    ],
)
def test_invite_forms(raw: str) -> None:
    assert parse_link(raw) == LinkTarget(LinkKind.INVITE, HASH)


def test_invite_hash_is_case_sensitive() -> None:
    target = parse_link(f"https://t.me/joinchat/{HASH}")

    assert target.canonical_url == f"https://t.me/+{HASH}"
    assert target.dedupe_key == f"invite:{HASH}"
    assert target.dedupe_key == parse_link(f"tg://join?invite={HASH}").dedupe_key
    assert target.dedupe_key != parse_link(f"t.me/+{HASH.lower()}").dedupe_key


@pytest.mark.parametrize("length", [8, 16, 22, 64])
def test_invite_hash_length_bounds(length: int) -> None:
    assert parse_link(f"t.me/+{'A' * length}").value == "A" * length


@pytest.mark.parametrize(
    "raw",
    [
        "t.me/+short",
        "t.me/+" + "A" * 65,
        "t.me/+abc$defgh123",
        "https://t.me/+",
        "t.me/+/",
        "t.me/joinchat/한글해시한글해시",
        "tg://join?invite=short",
    ],
)
def test_bad_invite_hash(raw: str) -> None:
    with pytest.raises(LinkError, match="초대 링크 형식이 올바르지 않아요"):
        parse_link(raw)


@pytest.mark.parametrize("raw", ["t.me/joinchat", "https://t.me/joinchat/"])
def test_truncated_joinchat_link(raw: str) -> None:
    with pytest.raises(LinkError, match="초대 링크가 잘렸어요"):
        parse_link(raw)


@pytest.mark.parametrize("raw", ["t.me/+821012345678", "https://t.me/+14155550123"])
def test_phone_links_are_rejected(raw: str) -> None:
    with pytest.raises(LinkError, match="전화번호 링크"):
        parse_link(raw)


# ---------------------------------------------------------------------------
# 그 밖의 잘못된 입력
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", "<>", " < > "])
def test_empty_input(raw: str) -> None:
    with pytest.raises(LinkError, match="링크가 비어 있어요"):
        parse_link(raw)


def test_too_long_input() -> None:
    with pytest.raises(LinkError, match="링크가 너무 길어요"):
        parse_link("https://t.me/" + "a" * 300)


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/durov",
        "https://t.me.evil.com/durov",
        "telegram.org/durov",
        "web.telegram.org/k/#@durov",
        "durov.t.me",
        "x.y",
        "a/b",
        "t.me\\durov",
        "://",
        "https://",
        "////",
    ],
)
def test_other_hosts_are_rejected(raw: str) -> None:
    with pytest.raises(LinkError, match=r"텔레그램 링크\(t\.me\)가 아니에요"):
        parse_link(raw)


@pytest.mark.parametrize("raw", ["t.me", "https://t.me", "https://t.me/", "t.me//"])
def test_host_without_path(raw: str) -> None:
    with pytest.raises(LinkError, match="그룹을 가리키는 링크가 아니에요"):
        parse_link(raw)


def test_private_message_link_explains_what_to_do() -> None:
    with pytest.raises(LinkError, match="초대 링크를 넣어 주세요"):
        parse_link("https://t.me/c/1234567890/55")


def test_folder_link_is_not_supported() -> None:
    with pytest.raises(LinkError, match="폴더 링크는 지원하지 않아요"):
        parse_link("https://t.me/addlist/AbCdEf123456")


@pytest.mark.parametrize(
    "raw",
    ["tg://", "tg://?", "tg://join", "tg://msg?text=hi", "tg://resolve?phone=821012345678"],
)
def test_unsupported_tg_scheme_links(raw: str) -> None:
    with pytest.raises(LinkError, match="지원하지 않는 tg:// 링크예요"):
        parse_link(raw)


@pytest.mark.parametrize("raw", ["[t.me/durov]", "https://[t.me]/durov", "tg://[join"])
def test_broken_brackets_raise_link_error_not_a_bare_value_error(raw: str) -> None:
    with pytest.raises(LinkError, match="링크 형식이 올바르지 않아요"):
        parse_link(raw)


def test_link_error_is_a_value_error_with_korean_message() -> None:
    with pytest.raises(ValueError) as caught:
        parse_link("https://example.com/durov")

    assert type(caught.value) is LinkError
    assert str(caught.value).endswith("요.")
