"""데이터 모델. 이 파일이 저장 구조의 기준이다."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow

# ---------------------------------------------------------------------------
# 열거형 (문자열로 저장한다)
# ---------------------------------------------------------------------------


class AccountStatus(StrEnum):
    CONNECTING = "connecting"  # 접속 시도 중
    ACTIVE = "active"  # 정상
    FLOOD_WAIT = "flood_wait"  # 텔레그램 요청 제한으로 대기 중 (flood_until 까지)
    REAUTH_REQUIRED = "reauth_required"  # 세션이 만료·해지됨. 다시 로그인해야 한다
    BANNED = "banned"  # 계정이 정지됨
    ERROR = "error"  # 그 밖의 오류로 끊김 (자동 재시도)
    OFFLINE = "offline"  # 꺼져 있음 (enabled=False 이거나 엔진이 내려가 있음)


class GroupStatus(StrEnum):
    QUEUED = "queued"  # 가입 대기열에 있음
    JOINING = "joining"  # 가입 시도 중
    REQUESTED = "requested"  # 입장 요청을 보냈고 관리자 승인을 기다리는 중
    JOINED = "joined"  # 가입됨
    FAILED = "failed"  # 가입 실패 (error_code, status_detail 참고)
    LEFT = "left"  # 나갔거나 쫓겨남


class GroupKind(StrEnum):
    GROUP = "group"  # 일반 그룹
    SUPERGROUP = "supergroup"  # 슈퍼그룹
    CHANNEL = "channel"  # 방송 채널 (유저 채팅이 없어 수집되지 않는다)


class LinkKind(StrEnum):
    PUBLIC = "public"  # t.me/username
    INVITE = "invite"  # t.me/+hash, t.me/joinchat/hash
    EXISTING = "existing"  # 이미 들어가 있던 그룹을 불러온 것


class RuleKind(StrEnum):
    KEYWORD = "keyword"
    ACTIVITY = "activity"


class MatchMode(StrEnum):
    ANY = "any"  # 키워드 중 하나라도 포함
    ALL = "all"  # 키워드 모두 포함


class LeadStatus(StrEnum):
    NEW = "new"  # 새로 수집됨
    REVIEWED = "reviewed"  # 확인함
    CONTACTED = "contacted"  # 연락함
    EXCLUDED = "excluded"  # 제외 (이후 감지되어도 기록하지 않는다)


class LogLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogCategory(StrEnum):
    ACCOUNT = "account"
    GROUP = "group"
    COLLECT = "collect"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# 테이블
# ---------------------------------------------------------------------------


class Admin(Base):
    """관리자 한 명. 행은 최대 하나다."""

    __tablename__ = "admin"

    id: Mapped[int] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    """비밀번호를 바꾸면 올려서 기존 로그인 쿠키를 모두 무효화한다."""
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    """JSON 으로 직렬화한 값."""


class Account(Base):
    """내 텔레그램 계정(세션) 하나."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str | None] = mapped_column(String(64))
    """콘솔에서 붙인 별칭."""
    phone: Mapped[str | None] = mapped_column(String(32))
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    session_enc: Mapped[str | None] = mapped_column(Text)
    """암호화한 Telethon StringSession."""

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    """사용자가 켜고 끄는 값. False 면 접속하지 않는다."""
    status: Mapped[str] = mapped_column(String(24), default=AccountStatus.OFFLINE)
    status_detail: Mapped[str | None] = mapped_column(String(500))
    flood_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_join_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    groups: Mapped[list[Group]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Group(Base):
    """계정 하나가 들어가 있거나 들어가려는 그룹."""

    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("account_id", "tg_chat_id", name="uq_group_account_chat"),
        Index("ix_groups_status", "status"),
        Index("ix_groups_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))

    source_link: Mapped[str | None] = mapped_column(String(300))
    """사용자가 넣은 링크 원문."""
    link_kind: Mapped[str] = mapped_column(String(16), default=LinkKind.PUBLIC)
    public_username: Mapped[str | None] = mapped_column(String(64))
    invite_hash: Mapped[str | None] = mapped_column(String(128))

    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    """Telethon 의 marked peer id (슈퍼그룹은 -100…, 일반 그룹은 음수). 가입 전에는 비어 있다."""
    title: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str | None] = mapped_column(String(16))
    member_count: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(16), default=GroupStatus.QUEUED)
    status_detail: Mapped[str | None] = mapped_column(String(500))
    """사람이 읽는 한국어 설명."""
    error_code: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    monitoring: Mapped[bool] = mapped_column(Boolean, default=True)
    messages_seen: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    joined_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="groups")


rule_groups = Table(
    "rule_groups",
    Base.metadata,
    Column("rule_id", ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class Rule(Base):
    """수집 규칙. 키워드 규칙이거나 활동량 규칙이다."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # 키워드 규칙
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    match_mode: Mapped[str] = mapped_column(String(8), default=MatchMode.ANY)

    # 활동량 규칙: 한 그룹에서 window_hours 시간 동안 min_messages 개 이상 보낸 사람
    min_messages: Mapped[int | None] = mapped_column(Integer)
    window_hours: Mapped[int | None] = mapped_column(Integer)

    all_groups: Mapped[bool] = mapped_column(Boolean, default=True)
    """True 면 감시 중인 모든 그룹에 적용. False 면 groups 에 있는 그룹에만."""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    groups: Mapped[list[Group]] = relationship(secondary=rule_groups, lazy="selectin")


class Lead(Base):
    """수집된 유저 한 명. 텔레그램 유저 id 기준으로 하나다."""

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_first_seen", "first_seen_at"),
        Index("ix_leads_last_seen", "last_seen_at"),
        Index("ix_leads_status", "status"),
        Index("ix_leads_username", "username"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(64))
    """@ 없이, 원래 대소문자 그대로."""
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))

    status: Mapped[str] = mapped_column(String(16), default=LeadStatus.NEW)
    note: Mapped[str | None] = mapped_column(Text)

    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    first_kind: Mapped[str] = mapped_column(String(16))
    """처음 수집된 계기 (keyword / activity). 추이 그래프의 계열 구분에 쓴다."""
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_hit_id: Mapped[int | None] = mapped_column(Integer)
    """가장 최근 Hit 의 id (목록에서 바로 보여 주려고 둔 포인터, FK 아님)."""

    hits: Mapped[list[Hit]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", passive_deletes=True
    )


class Hit(Base):
    """감지 한 건. 누가, 어느 그룹에서, 어떤 규칙에 걸렸는지."""

    __tablename__ = "hits"
    __table_args__ = (
        Index("ix_hits_created", "created_at"),
        Index("ix_hits_lead", "lead_id", "created_at"),
        Index("ix_hits_rule", "rule_id"),
        Index("ix_hits_group", "group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))

    kind: Mapped[str] = mapped_column(String(16))
    rule_name: Mapped[str] = mapped_column(String(80))
    """규칙이 지워져도 남도록 저장해 두는 이름."""
    group_title: Mapped[str | None] = mapped_column(String(255))

    # 키워드 감지
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    """문장에서 실제로 걸린 키워드들."""
    excerpt: Mapped[str | None] = mapped_column(String(400))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)

    # 활동량 감지
    message_count: Mapped[int | None] = mapped_column(Integer)
    window_hours: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="hits")


class BlocklistEntry(Base):
    """수집하지 않을 아이디. 내 계정들은 따로 넣지 않아도 자동으로 빠진다."""

    __tablename__ = "blocklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    """@ 없이 소문자."""
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ActivityBucket(Base):
    """활동량 집계. (그룹, 유저, 시각 단위) 별 메시지 수."""

    __tablename__ = "activity_buckets"
    __table_args__ = (Index("ix_activity_hour", "hour"),)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hour: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    """UTC 기준 정시로 내림한 시각."""
    count: Mapped[int] = mapped_column(Integer, default=0)


class EventLog(Base):
    """활동 기록."""

    __tablename__ = "event_logs"
    __table_args__ = (Index("ix_event_logs_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(10), default=LogLevel.INFO)
    category: Mapped[str] = mapped_column(String(12), default=LogCategory.SYSTEM)
    message: Mapped[str] = mapped_column(String(500))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
