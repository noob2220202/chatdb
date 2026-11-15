"""키워드 매칭과 문장 발췌. 순수 함수만 둔다."""

from __future__ import annotations

import unicodedata

from .models import MatchMode

EXCERPT_LENGTH = 200


def normalize(text: str) -> str:
    """비교용 정규화: 전각/반각·호환 문자를 통일하고 대소문자를 없앤다."""
    return unicodedata.normalize("NFKC", text).casefold()


def _squash(text: str) -> str:
    """공백을 모두 뺀다. '업체 추천' 과 '업체추천' 을 같게 보려고 쓴다."""
    return "".join(text.split())


def _contains(norm_text: str, squashed_text: str, keyword: str) -> bool:
    norm_kw = normalize(keyword).strip()
    if not norm_kw:
        return False
    if norm_kw in norm_text:
        return True
    squashed_kw = _squash(norm_kw)
    # 띄어쓰기가 있는 키워드만 공백 무시 비교를 한다 (짧은 한 단어 키워드의 오탐 방지).
    return squashed_kw != norm_kw and squashed_kw in squashed_text


def match_keywords(
    text: str,
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
    mode: str = MatchMode.ANY,
) -> list[str]:
    """문장에서 걸린 키워드 목록을 돌려준다. 규칙에 맞지 않으면 빈 리스트.

    - mode=ANY: 키워드 중 하나라도 있으면 통과, 걸린 것만 돌려준다.
    - mode=ALL: 키워드가 모두 있어야 통과.
    - exclude_keywords 중 하나라도 있으면 탈락.
    - 대소문자, 전각/반각을 구분하지 않고, 띄어쓰기가 있는 키워드는 붙여 쓴 경우도 잡는다.
    """
    if not text or not keywords:
        return []
    norm_text = normalize(text)
    squashed_text = _squash(norm_text)

    for word in exclude_keywords or []:
        if _contains(norm_text, squashed_text, word):
            return []

    matched = [kw for kw in keywords if _contains(norm_text, squashed_text, kw)]
    if not matched:
        return []
    if mode == MatchMode.ALL and len(matched) != len([k for k in keywords if normalize(k).strip()]):
        return []
    return matched


def make_excerpt(text: str, matched: list[str], max_length: int = EXCERPT_LENGTH) -> str:
    """걸린 키워드 주변을 잘라 한 줄 발췌를 만든다. 잘린 쪽에는 … 를 붙인다."""
    flat = " ".join(text.split())
    if len(flat) <= max_length:
        return flat

    lowered = flat.casefold()
    position = -1
    for kw in matched:
        idx = lowered.find(" ".join(kw.split()).casefold())
        if idx != -1 and (position == -1 or idx < position):
            position = idx
    if position == -1:
        position = 0

    start = max(0, position - max_length // 3)
    end = min(len(flat), start + max_length)
    start = max(0, end - max_length)
    snippet = flat[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(flat):
        snippet = snippet + "…"
    return snippet
