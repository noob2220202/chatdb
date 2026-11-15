"""API 요청·응답 형식. 프론트엔드 타입은 이 파일에서 나온 OpenAPI 로 생성한다."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    AccountStatus,
    GroupKind,
    GroupStatus,
    LeadStatus,
    LinkKind,
    LogCategory,
    LogLevel,
    MatchMode,
    RuleKind,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(ApiModel):
    """단순 확인 응답."""

    ok: bool = True


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------


class AuthStatus(ApiModel):
    setup_required: bool
    """아직 관리자 비밀번호를 만들지 않았다."""
    authenticated: bool
    demo: bool


class SetupRequest(ApiModel):
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(ApiModel):
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


# ---------------------------------------------------------------------------
# 계정
# ---------------------------------------------------------------------------


class AccountOut(ApiModel):
    id: int
    label: str | None
    display_name: str
    """별칭 → 이름 → @아이디 → 번호 순으로 고른 표시 이름."""
    phone_masked: str | None
    """가운데를 가린 번호. 예: +82 10-••••-3421"""
    tg_user_id: int | None
    first_name: str | None
    last_name: str | None
    username: str | None
    enabled: bool
    status: AccountStatus
    status_detail: str | None
    flood_until: datetime | None
    last_connected_at: datetime | None
    created_at: datetime
    joined_count: int
    """가입된 그룹 수."""
    pending_count: int
    """대기열·가입 시도 중·입장 요청 중인 그룹 수."""
    max_groups: int
    """계정 하나에 넣을 수 있는 그룹 수(설정값)."""


class AccountUpdate(ApiModel):
    label: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None


class LoginStartRequest(ApiModel):
    phone: str = Field(min_length=5, max_length=32)


class LoginStartResponse(ApiModel):
    login_id: str
    phone: str
    code_via: Literal["app", "sms", "call", "other"]
    """인증 코드가 전달된 경로."""
    expires_at: datetime


class LoginCodeRequest(ApiModel):
    login_id: str
    code: str = Field(min_length=3, max_length=12)


class LoginPasswordRequest(ApiModel):
    login_id: str
    password: str = Field(min_length=1, max_length=256)


class LoginStepResponse(ApiModel):
    status: Literal["done", "password_required"]
    account: AccountOut | None = None
    password_hint: str | None = None


class SessionImportRequest(ApiModel):
    session_string: str = Field(min_length=20, max_length=4000)
    label: str | None = Field(default=None, max_length=64)


class DialogOut(ApiModel):
    """계정이 이미 들어가 있는 그룹."""

    tg_chat_id: int
    title: str
    username: str | None
    kind: GroupKind
    member_count: int | None
    already_added: bool
    """이미 이 계정의 감시 목록에 있다."""


class DialogImportRequest(ApiModel):
    tg_chat_ids: list[int] = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# 그룹
# ---------------------------------------------------------------------------


class GroupOut(ApiModel):
    id: int
    account_id: int
    account_name: str
    source_link: str | None
    link_kind: LinkKind
    public_username: str | None
    tg_chat_id: int | None
    title: str | None
    display_title: str
    """제목이 아직 없으면 @아이디나 링크로 대신한 표시 이름."""
    kind: GroupKind | None
    member_count: int | None
    status: GroupStatus
    status_detail: str | None
    error_code: str | None
    attempts: int
    next_attempt_at: datetime | None
    monitoring: bool
    messages_seen: int
    last_message_at: datetime | None
    joined_at: datetime | None
    created_at: datetime
    lead_count: int
    """이 그룹에서 수집된 유저 수."""


class GroupJoinRequest(ApiModel):
    links: list[str] = Field(min_length=1, max_length=200)
    account_id: int | None = None
    """비우면 여유가 가장 많은 계정에 자동으로 나눠 넣는다."""


class GroupJoinItem(ApiModel):
    input: str
    outcome: Literal["queued", "duplicate", "invalid", "no_capacity"]
    reason: str | None = None
    group: GroupOut | None = None


class GroupJoinResponse(ApiModel):
    items: list[GroupJoinItem]
    queued: int


class GroupUpdate(ApiModel):
    monitoring: bool | None = None


# ---------------------------------------------------------------------------
# 수집 규칙
# ---------------------------------------------------------------------------


def _clean_keywords(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        word = " ".join(raw.split())
        if not word:
            continue
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(word[:60])
    return out


class RuleFields(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    kind: RuleKind
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list, max_length=100)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=100)
    match_mode: MatchMode = MatchMode.ANY
    min_messages: int | None = Field(default=None, ge=2, le=10000)
    window_hours: int | None = Field(default=None, ge=1, le=720)
    all_groups: bool = True
    group_ids: list[int] = Field(default_factory=list, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("규칙 이름을 입력해 주세요.")
        return v

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return _clean_keywords(v)


class RuleCreate(RuleFields):
    @model_validator(mode="after")
    def _check(self) -> RuleCreate:
        if self.kind == RuleKind.KEYWORD:
            if not self.keywords:
                raise ValueError("키워드를 하나 이상 넣어 주세요.")
        else:
            if self.min_messages is None or self.window_hours is None:
                raise ValueError("메시지 수와 기간을 정해 주세요.")
        if not self.all_groups and not self.group_ids:
            raise ValueError("적용할 그룹을 하나 이상 골라 주세요.")
        return self


class RuleUpdate(ApiModel):
    """보낸 필드만 바꾼다. kind 는 바꿀 수 없다."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    keywords: list[str] | None = Field(default=None, max_length=100)
    exclude_keywords: list[str] | None = Field(default=None, max_length=100)
    match_mode: MatchMode | None = None
    min_messages: int | None = Field(default=None, ge=2, le=10000)
    window_hours: int | None = Field(default=None, ge=1, le=720)
    all_groups: bool | None = None
    group_ids: list[int] | None = Field(default=None, max_length=2000)

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _clean(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_keywords(v)


class RuleOut(ApiModel):
    id: int
    name: str
    kind: RuleKind
    enabled: bool
    keywords: list[str]
    exclude_keywords: list[str]
    match_mode: MatchMode
    min_messages: int | None
    window_hours: int | None
    all_groups: bool
    group_ids: list[int]
    created_at: datetime
    updated_at: datetime
    lead_count: int
    """이 규칙으로 수집된 유저 수."""
    hit_count: int
    last_hit_at: datetime | None


# ---------------------------------------------------------------------------
# 수집함
# ---------------------------------------------------------------------------


class HitOut(ApiModel):
    id: int
    kind: RuleKind
    rule_id: int | None
    rule_name: str
    group_id: int | None
    group_title: str | None
    keywords: list[str]
    excerpt: str | None
    message_count: int | None
    window_hours: int | None
    created_at: datetime


class LeadOut(ApiModel):
    id: int
    tg_user_id: int
    username: str
    first_name: str | None
    last_name: str | None
    display_name: str
    status: LeadStatus
    note: str | None
    hit_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    last_hit: HitOut | None


class LeadDetail(LeadOut):
    hits: list[HitOut]
    """최근 감지 기록 (최대 100건, 최신순)."""
    group_titles: list[str]
    """감지된 적 있는 그룹 이름들."""


class LeadUpdate(ApiModel):
    status: LeadStatus | None = None
    note: str | None = Field(default=None, max_length=2000)


class LeadListResponse(ApiModel):
    items: list[LeadOut]
    total: int
    page: int
    page_size: int
    status_counts: dict[str, int]
    """상태별 인원 (상태 필터를 뺀 나머지 필터 기준). 키는 LeadStatus 값."""


class LeadBulkRequest(ApiModel):
    ids: list[int] = Field(min_length=1, max_length=5000)
    action: Literal["set_status", "delete", "block"]
    """block 은 제외 상태로 바꾸고 제외 목록에도 올린다."""
    status: LeadStatus | None = None

    @model_validator(mode="after")
    def _check(self) -> LeadBulkRequest:
        if self.action == "set_status" and self.status is None:
            raise ValueError("바꿀 상태를 골라 주세요.")
        return self


class BulkResult(ApiModel):
    affected: int


# ---------------------------------------------------------------------------
# 제외 목록
# ---------------------------------------------------------------------------


class BlocklistOut(ApiModel):
    id: int
    username: str
    note: str | None
    created_at: datetime


class BlocklistCreate(ApiModel):
    usernames: list[str] = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# 활동 기록
# ---------------------------------------------------------------------------


class LogOut(ApiModel):
    id: int
    level: LogLevel
    category: LogCategory
    message: str
    account_id: int | None
    account_name: str | None
    group_id: int | None
    group_title: str | None
    created_at: datetime


class LogListResponse(ApiModel):
    items: list[LogOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


class SettingsOut(ApiModel):
    tg_api_id: int | None
    tg_api_hash_set: bool
    """api_hash 가 저장돼 있는지 (값 자체는 내려주지 않는다)."""
    tg_api_source: Literal["settings", "env", "none"]
    max_groups_per_account: int
    join_interval_seconds: int
    """한 계정이 그룹 하나에 가입한 뒤 다음 가입까지 쉬는 시간(초)."""
    retention_days: int
    """감지 기록 보관 일수. 0 이면 지우지 않는다."""
    store_excerpts: bool
    """키워드가 걸린 문장 발췌를 저장할지."""
    timezone: str
    demo: bool
    version: str


class SettingsUpdate(ApiModel):
    tg_api_id: int | None = Field(default=None, ge=1)
    tg_api_hash: str | None = Field(default=None, min_length=8, max_length=64)
    max_groups_per_account: int | None = Field(default=None, ge=1, le=500)
    join_interval_seconds: int | None = Field(default=None, ge=30, le=3600)
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    store_excerpts: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# 개요
# ---------------------------------------------------------------------------


class FeedItem(ApiModel):
    """실시간 감지 한 줄."""

    hit_id: int
    created_at: datetime
    kind: RuleKind
    rule_id: int | None
    rule_name: str
    group_id: int | None
    group_title: str | None
    keywords: list[str]
    excerpt: str | None
    message_count: int | None
    window_hours: int | None
    lead_id: int
    username: str
    display_name: str
    is_new_lead: bool
    """이 감지로 처음 수집된 유저다."""


class DayPoint(ApiModel):
    date: str
    """설정된 시간대 기준 날짜 (YYYY-MM-DD)."""
    keyword: int
    activity: int


class TopGroup(ApiModel):
    group_id: int
    title: str
    leads: int


class RuleTotal(ApiModel):
    rule_id: int
    name: str
    kind: RuleKind
    enabled: bool
    leads: int


class OverviewOut(ApiModel):
    today_new: int
    yesterday_new: int
    total_leads: int
    accounts_connected: int
    accounts_total: int
    groups_monitoring: int
    """가입돼 있고 감시가 켜진 그룹 수."""
    groups_capacity: int
    """계정 수 × 계정당 그룹 수."""
    join_requests_pending: int
    """승인을 기다리는 입장 요청 수."""
    join_queue: int
    """가입 대기열에 남은 수."""
    series: list[DayPoint]
    top_groups: list[TopGroup]
    rule_totals: list[RuleTotal]
    accounts: list[AccountOut]
    recent_hits: list[FeedItem]


# ---------------------------------------------------------------------------
# 오류
# ---------------------------------------------------------------------------


class ErrorOut(ApiModel):
    """모든 오류 응답의 본문. detail 은 화면에 그대로 보여 줄 수 있는 한국어 문장이다."""

    detail: str
    code: str | None = None
    retry_after: int | None = None
