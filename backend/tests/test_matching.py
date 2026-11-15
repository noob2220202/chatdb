"""키워드 매칭과 발췌 테스트."""

from __future__ import annotations

import unicodedata

import pytest

from app.matching import EXCERPT_LENGTH, make_excerpt, match_keywords, normalize
from app.models import MatchMode

FILLER = "가" * 300

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ＡＢＣ　１２３", "abc 123"),  # 전각 영문·숫자·공백
        ("Telegram VIP", "telegram vip"),
        ("Straße", "strasse"),
        ("㈜카카오", "(주)카카오"),  # 호환 문자
        ("①번", "1번"),
        ("ｶｶｵ", "カカオ"),  # 반각 가나
        (unicodedata.normalize("NFD", "추천"), "추천"),  # 풀어쓴 자모
        ("", ""),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# ---------------------------------------------------------------------------
# match_keywords
# ---------------------------------------------------------------------------


def test_returns_matched_keywords_in_rule_order_with_original_spelling() -> None:
    matched = match_keywords("견적 문의드립니다. 업체 추천도 부탁해요", ["추천", "환불", "견적"])

    assert matched == ["추천", "견적"]


@pytest.mark.parametrize(
    ("text", "keywords"),
    [
        ("", ["추천"]),
        ("추천 부탁드려요", []),
        ("추천 부탁드려요", ["", "   "]),
        ("   \n ", ["추천"]),
        ("안녕하세요", ["추천"]),
    ],
)
def test_no_match(text: str, keywords: list[str]) -> None:
    assert match_keywords(text, keywords) == []


@pytest.mark.parametrize(
    ("text", "keyword"),
    [
        ("vip 문의", "VIP"),
        ("VIP 문의", "vip"),
        ("ＶＩＰ 문의", "vip"),  # 전각 본문
        ("vip 문의", "ＶＩＰ"),  # 전각 키워드
        ("ＴＥＬＥＧＲＡＭ　ＶＩＰ", "telegram vip"),  # 전각 공백
        ("STRASSE 10", "straße"),
        ("①번 매물 문의", "1번"),
        ("ㅋㅋㅋㅋ 대박", "ㅋㅋ"),
        (unicodedata.normalize("NFD", "추천 부탁드려요"), "추천"),
        ("추천 부탁드려요", unicodedata.normalize("NFD", "추천")),
    ],
)
def test_case_width_and_composition_are_ignored(text: str, keyword: str) -> None:
    assert match_keywords(text, [keyword]) == [keyword]


@pytest.mark.parametrize(
    "text",
    [
        "업체 추천 부탁드려요",
        "업체추천 부탁드려요",
        "업체  추천 부탁드려요",
        "업체\n추천 부탁드려요",
        "업체\t추천",
        "업체　추천",  # 전각 공백
        "업 체 추 천",
        "좋은업체추천좀요",
    ],
)
def test_spaced_keyword_matches_any_spacing(text: str) -> None:
    assert match_keywords(text, ["업체 추천"]) == ["업체 추천"]


@pytest.mark.parametrize("keyword", ["업체  추천", "  업체 추천  ", "업체　추천", "업체\t추천"])
def test_keyword_spacing_is_normalized_too(keyword: str) -> None:
    assert match_keywords("업체추천 부탁드려요", [keyword]) == [keyword]
    assert match_keywords("업체 추천 부탁드려요", [keyword]) == [keyword]


def test_single_word_keyword_does_not_match_across_spaces() -> None:
    # 한 단어 키워드는 붙여 쓴 것만 잡는다(짧은 단어의 오탐을 막으려는 의도).
    assert match_keywords("업체추천해주세요", ["업체추천"]) == ["업체추천"]
    assert match_keywords("업체 추천 해주세요", ["업체추천"]) == []
    assert match_keywords("누가 방금 왔어요", ["가방"]) == []


def test_exclude_keyword_drops_the_whole_message() -> None:
    assert match_keywords("대출 상담 문의", ["대출"], ["광고"]) == ["대출"]
    assert match_keywords("대출 광고 아닙니다", ["대출"], ["광고"]) == []
    assert match_keywords("대출 문의 (홍보X)", ["대출"], ["광고", "홍보"]) == []


@pytest.mark.parametrize("text", ["대출 광고문의 환영", "대출 ＡＤ 문의", "대출 Ad 문의"])
def test_exclude_keywords_use_the_same_normalization(text: str) -> None:
    assert match_keywords(text, ["대출"], ["광고 문의", "ad"]) == []


def test_blank_exclude_keywords_are_ignored() -> None:
    assert match_keywords("대출 문의", ["대출"], ["", "  "]) == ["대출"]
    assert match_keywords("대출 문의", ["대출"], None) == ["대출"]
    assert match_keywords("대출 문의", ["대출"], []) == ["대출"]


def test_mode_any_is_the_default() -> None:
    assert match_keywords("서울 전세 구합니다", ["서울", "매매"]) == ["서울"]
    assert match_keywords("서울 전세 구합니다", ["서울", "매매"], None, MatchMode.ANY) == ["서울"]


def test_mode_all_needs_every_keyword() -> None:
    keywords = ["서울", "아파트 매매"]

    assert match_keywords("서울 전세 구합니다", keywords, None, MatchMode.ALL) == []
    assert match_keywords("아파트매매 알아봐요", keywords, None, MatchMode.ALL) == []
    assert match_keywords("서울 아파트매매 알아봐요", keywords, None, MatchMode.ALL) == keywords
    assert match_keywords("서울 아파트 매매", keywords, None, "all") == keywords


def test_mode_all_ignores_blank_keywords() -> None:
    assert match_keywords("추천 부탁", ["추천", " ", ""], None, MatchMode.ALL) == ["추천"]
    assert match_keywords("추천 부탁", [" ", ""], None, MatchMode.ALL) == []


def test_mode_all_still_respects_exclude_keywords() -> None:
    assert match_keywords("서울 매매 광고", ["서울", "매매"], ["광고"], MatchMode.ALL) == []


# ---------------------------------------------------------------------------
# make_excerpt
# ---------------------------------------------------------------------------


def test_short_text_is_returned_whole_on_one_line() -> None:
    assert make_excerpt("  여러\n줄\t메시지   입니다 ", ["메시지"]) == "여러 줄 메시지 입니다"
    assert make_excerpt("", []) == ""


def test_text_at_the_limit_is_not_cut() -> None:
    exact = "가" * EXCERPT_LENGTH

    assert make_excerpt(exact, ["추천"]) == exact
    assert make_excerpt(exact + "나", ["추천"]) == exact + "…"


def test_keyword_at_the_start_cuts_only_the_tail() -> None:
    excerpt = make_excerpt("추천 " + FILLER, ["추천"])

    assert excerpt.startswith("추천 가가")
    assert excerpt.endswith("가…")
    assert len(excerpt) == EXCERPT_LENGTH + 1


def test_keyword_in_the_middle_keeps_context_on_both_sides() -> None:
    excerpt = make_excerpt(f"{FILLER} 추천 부탁드려요 {FILLER}", ["추천"])

    assert excerpt.startswith("…가") and excerpt.endswith("가…")
    assert len(excerpt) == EXCERPT_LENGTH + 2
    assert "\n" not in excerpt
    # 키워드 앞에는 3분의 1쯤, 뒤에는 나머지를 보여 준다.
    assert 60 <= excerpt.index("추천") <= 70


def test_keyword_at_the_end_cuts_only_the_head() -> None:
    excerpt = make_excerpt(f"{FILLER} 추천 부탁드려요", ["추천"])

    assert excerpt.startswith("…가")
    assert excerpt.endswith("추천 부탁드려요")
    assert len(excerpt) == EXCERPT_LENGTH + 1


def test_earliest_matched_keyword_anchors_the_excerpt() -> None:
    text = f"{FILLER} 추천 {FILLER} 견적 문의"

    excerpt = make_excerpt(text, ["견적", "추천"])

    assert "추천" in excerpt
    assert "견적" not in excerpt


@pytest.mark.parametrize(
    ("fragment", "keyword"),
    [
        ("업체추천", "업체 추천"),  # 붙여 쓴 본문
        ("업 체 추 천", "업체 추천"),  # 띄엄띄엄 쓴 본문
        ("업체 추천", "업체  추천"),  # 키워드 쪽 공백이 더 많음
        ("ＶＩＰ", "vip"),  # 전각 본문
        ("vip", "ＶＩＰ"),  # 전각 키워드
        ("Vip", "VIP"),  # 대소문자
        ("㈜카카오", "(주)카카오"),  # 정규화하면 글자 수가 달라짐
    ],
)
def test_long_text_excerpt_finds_keyword_the_way_matching_does(fragment: str, keyword: str) -> None:
    text = f"{FILLER} 여기 {fragment} 문의 {FILLER}"
    matched = match_keywords(text, [keyword])
    assert matched == [keyword]

    excerpt = make_excerpt(text, matched)

    assert fragment in excerpt
    assert len(excerpt) <= EXCERPT_LENGTH + 2


def test_characters_that_grow_when_normalized_do_not_shift_the_window() -> None:
    # 'ß' 는 정규화하면 'ss' 두 글자가 된다. 원문 위치를 따라가야 키워드가 발췌 안에 남는다.
    excerpt = make_excerpt("ß" * 300 + " 추천 부탁드려요 " + FILLER, ["추천"])

    assert "추천 부탁드려요" in excerpt
    assert len(excerpt) == EXCERPT_LENGTH + 2


@pytest.mark.parametrize("matched", [[], ["없는말"], ["", "  "]])
def test_excerpt_falls_back_to_the_beginning(matched: list[str]) -> None:
    excerpt = make_excerpt("나" * 500, matched)

    assert excerpt == "나" * EXCERPT_LENGTH + "…"


def test_custom_max_length() -> None:
    excerpt = make_excerpt(f"{FILLER} 추천 {FILLER}", ["추천"], max_length=30)

    assert "추천" in excerpt
    assert len(excerpt) == 32
    assert excerpt.startswith("…") and excerpt.endswith("…")
