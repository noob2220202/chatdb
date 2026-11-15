"""데모 데이터.

계정이 하나도 없는 빈 DB 에서 처음 켜면, 30일 동안 운영해 온 것처럼 보이는 기록을 채운다.
그리고 켤 때마다 DB 에 있는 계정·그룹을 데모 게이트웨이의 세계에 다시 올려서, 다시 시작해도
같은 그룹에서 대화가 이어지게 한다.

관리자 계정은 만들지 않는다(콘솔의 첫 실행 화면이 만든다).
"""

from __future__ import annotations

import itertools
import logging
import math
import random
import string
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .context import AppContext
from .db import utcnow
from .links import LinkTarget
from .matching import make_excerpt, match_keywords
from .models import (
    Account,
    AccountStatus,
    ActivityBucket,
    BlocklistEntry,
    EventLog,
    Group,
    GroupKind,
    GroupStatus,
    Hit,
    Lead,
    LeadStatus,
    LinkKind,
    LogCategory,
    LogLevel,
    Rule,
    RuleKind,
)
from .security import Secrets
from .telegram.demo_gateway import (
    POOL_SIZE,
    SESSION_PREFIX,
    DemoGateway,
    IntentKind,
    demo_chat_cast,
    demo_join_plan,
    demo_population,
    intent_message,
)
from .telegram.gateway import TgChat, TgUser

logger = logging.getLogger("chatdb.demo")

_SEED = 20_240_611
HISTORY_DAYS = 30
TOTAL_LEADS = 4_800
RECENT_KEYWORD_LEADS = (52, 61, 44, 83, 97, 68, 89)
RECENT_ACTIVITY_LEADS = (22, 30, 22, 37, 46, 29, 39)
"""최근 7일 동안 날마다 새로 수집된 유저 수(오래된 날부터, 마지막이 오늘)."""
FLOOD_WAIT_MINUTES = 14

_POPULATION = 6_600
"""수집된 유저를 뽑을 사람 수. 아이디 없는 사람과 봇을 빼고도 TOTAL_LEADS 를 넉넉히 넘는다."""
_POOL_LEAD_SHARE = 0.8
"""지금 그룹에서 말하는 사람들 가운데 이미 수집돼 있는 비율. 나머지는 켜 두면 새로 수집된다."""
_CROSS_RULE_SHARE = 0.05
"""한 유저의 뒤이은 감지가 처음과 다른 규칙에 걸리는 비율."""
_SAME_GROUP_SHARE = 0.7
_TOP_GROUP_LEADS = (520, 430, 350, 280, 220, 120, 105)
"""이름난 그룹 일곱 곳에서 처음 수집된 유저 수. 앞의 다섯이 '많이 수집된 그룹' 1~5위다."""
_TOP_GROUP_MEMBERS = (18_420, 12_870, 9_640, 7_315, 6_208, 4_890, 4_120)

# 엔진·게이트웨이가 쓰는 문장과 같아야 한다.
_LOG_CONNECTED = "텔레그램에 연결됐어요."
_LOG_DISCONNECTED = "텔레그램과 연결이 끊겼어요. 곧 다시 연결해요."
_LOG_JOINED = "그룹에 들어갔어요."
_LOG_REQUESTED = "입장 요청을 보냈어요. 관리자가 승인하면 자동으로 가입돼요."
_LOG_APPROVED = "입장 요청이 승인됐어요."
_LOG_FLOOD_LIFTED = "텔레그램 요청 제한이 풀려서 다시 진행해요."
_LOG_JOIN_FAILED = "그룹에 들어가지 못했어요."
_DETAIL_REQUESTED = "입장 요청을 보냈어요. 관리자 승인을 기다리는 중이에요"
_DETAIL_FLOOD = "텔레그램이 요청을 잠시 제한했어요. 제한이 풀리면 이어서 진행해요."
_MSG_SESSION_EXPIRED = "세션이 만료됐어요. 다시 로그인해 주세요."
_MSG_INVITE_EXPIRED = "초대 링크가 만료됐어요."
_MSG_PRIVATE = "비공개 그룹이거나 이 계정이 차단돼 있어서 들어갈 수 없어요."


# ---------------------------------------------------------------------------
# 계정
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AccountSpec:
    name: str
    username: str
    phone: str
    tg_user_id: int
    joined: int
    """가입돼 있는 그룹 수."""
    first_joins: int
    """그 가운데 계정을 추가한 날 한꺼번에 들어간 그룹 수(나머지는 최근 며칠 사이에 들어갔다)."""


_ACCOUNTS: tuple[_AccountSpec, ...] = (
    _AccountSpec("지우", "jiwoo_cs", "+821052873421", 7_712_405_871, 20, 19),
    _AccountSpec("민호", "minho_sales", "+821091246608", 7_698_120_457, 20, 18),
    _AccountSpec("서연", "seoyeon_team", "+821033587714", 7_731_664_902, 19, 18),
    _AccountSpec("태양", "taeyang_office", "+821076412295", 7_745_093_318, 20, 17),
    _AccountSpec("하늘", "haneul_cs", "+821024936187", 7_759_281_640, 18, 16),
    _AccountSpec("도윤", "doyun_sales", "+821088015932", 7_764_930_125, 20, 18),
    _AccountSpec("예린", "yerin_team", "+821045620873", 7_780_417_556, 20, 19),
    _AccountSpec("준서", "junseo_office", "+821067391546", 7_793_852_071, 17, 15),
    _AccountSpec("수아", "sua_cs", "+821029748316", 7_806_245_983, 20, 14),
    _AccountSpec("건우", "gunwoo_sales", "+821053162479", 7_819_670_234, 13, 13),
)
_FLOODED = 6  # 예린: 요청 제한 중
_EXPIRED = 9  # 건우: 세션 만료
EXPIRED_SESSION = f"{SESSION_PREFIX}{_EXPIRED + 1}"
"""건우 계정이 처음 받은 세션. 켤 때마다 만료된 것으로 친다(다시 로그인하면 새 세션을 받는다)."""
_SEEDED_USER_IDS = {spec.tg_user_id: index for index, spec in enumerate(_ACCOUNTS)}

# 입장 요청·대기열·실패 그룹의 링크. 데모 게이트웨이가 이 링크에 내는 결과와 같은 상태로 넣는다.
_APPROVED_SOON = "MuxkSvLi-B9h619t"
_REQUEST_LINKS: tuple[LinkTarget, ...] = tuple(
    LinkTarget(LinkKind.INVITE, invite_hash)
    for invite_hash in (
        "RRrU7Uwf2bUMPTWP",  # 하늘
        "uZ_cQEpdp-UCS-aE",  # 준서
        _APPROVED_SOON,  # 서연. 켜 두면 승인된다
        "fCAOgqAs57nBLBnm",  # 건우
        "vYoduuUo7V_L51r_",  # 건우
        "Y7YXwI8n4CxTqNmJ",  # 건우
    )
)
HELD_REQUESTS = frozenset(link.value for link in _REQUEST_LINKS) - {_APPROVED_SOON}
"""승인되지 않고 계속 기다리는 입장 요청(초대 해시)."""
_QUEUED_PUBLIC_LINK = LinkTarget(LinkKind.PUBLIC, "seller_lounge_kr")
_QUEUED_INVITE_LINK = LinkTarget(LinkKind.INVITE, "Md8uTw5ymfExtk-u")
_EXPIRED_LINK = LinkTarget(LinkKind.INVITE, "lAme0m45SpEooNGS")
_PRIVATE_LINK = LinkTarget(LinkKind.PUBLIC, "smallbiz_talk_kr")

# 계정이 들어가 있지만 감시 목록에는 없는 방들. '이미 들어가 있는 그룹 불러오기'에 나온다.
_EXTRA_DIALOGS: tuple[TgChat, ...] = (
    TgChat(-1_002_600_000_001, "셀러 공지 모음", "seller_notice_kr", GroupKind.CHANNEL, 15_204),
    TgChat(-1_002_600_000_002, "마케팅 자료 아카이브", "mkt_archive_kr", GroupKind.SUPERGROUP, 2_208),
    TgChat(-1_002_600_000_003, "이커머스 뉴스 브리핑", "ecommerce_brief", GroupKind.CHANNEL, 8_731),
    TgChat(-4_990_000_004, "동네 사장님 번개 모임", None, GroupKind.GROUP, 143),
    TgChat(-1_002_600_000_005, "소상공인 지원사업 알림", "sbiz_support_news", GroupKind.CHANNEL, 21_950),
    TgChat(-1_002_600_000_006, "셀러 중고 장비 나눔", None, GroupKind.SUPERGROUP, 612),
    TgChat(-1_002_600_000_007, "택배·물류 속보", None, GroupKind.CHANNEL, 3_412),
    TgChat(-4_990_000_008, "대학 동기 창업 수다", None, GroupKind.GROUP, 38),
)  # fmt: skip


# ---------------------------------------------------------------------------
# 규칙
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RuleSpec:
    name: str
    kind: RuleKind
    leads: int
    """이 규칙으로 처음 수집된 유저 수."""
    keywords: tuple[str, ...] = ()
    intent: IntentKind | None = None
    """키워드 규칙이 걸리는 글의 갈래."""
    min_messages: int | None = None
    window_hours: int | None = None


_RULES: tuple[_RuleSpec, ...] = (
    _RuleSpec("견적 문의", RuleKind.KEYWORD, 1_900, ("견적", "외주"), IntentKind.QUOTE),
    _RuleSpec(
        "업체 찾는 사람",
        RuleKind.KEYWORD,
        1_200,
        ("업체 추천", "업체 소개", "추천 부탁"),
        IntentKind.VENDOR,
    ),
    _RuleSpec("광고 대행", RuleKind.KEYWORD, 700, ("광고 대행", "마케팅 대행"), IntentKind.ADS),
    _RuleSpec("활발한 유저", RuleKind.ACTIVITY, 1_000, min_messages=30, window_hours=24),
)
_ACTIVITY_RULE = 3


# ---------------------------------------------------------------------------
# 그룹 이름
# ---------------------------------------------------------------------------

# 앞의 일곱 곳은 순서대로 가장 많이 수집되는 그룹이다. 나머지는 섞어서 쓴다.
_GROUP_TITLES: tuple[str, ...] = (
    "스마트스토어 셀러 모임", "해외구매대행 정보방", "쇼핑몰 창업 스터디", "퍼포먼스 마케터 모임",
    "도매 사입 정보 공유", "프리랜서 디자이너 네트워크", "위탁판매 초보방",
    # 온라인 판매
    "쿠팡 로켓그로스 셀러방", "쿠팡 윙 판매자 모임", "11번가 셀러 소통방",
    "지마켓·옥션 판매자 모임", "아마존 셀러 코리아", "쇼피 동남아 셀러방",
    "라쿠텐 일본 직판 스터디", "큐텐재팬 셀러 정보방", "알리·타오바오 소싱 공유",
    "1688 사입 대행 정보방", "오늘의집 입점 셀러 모임", "무신사 입점 브랜드 모임",
    "에이블리 셀러 소통방", "지그재그 판매자 정보 공유", "카카오 톡스토어 셀러방",
    "인스타 마켓 운영자 모임", "틱톡샵 셀러 스터디", "네이버 쇼핑라이브 판매자방",
    "와디즈 펀딩 메이커 모임", "텀블벅 창작자 정보방", "아이디어스 작가 모임",
    "자사몰 운영자 네트워크", "카페24 쇼핑몰 운영 팁", "고도몰·메이크샵 사장님방",
    "식스샵·아임웹 창업자 모임", "구매대행 실전 노하우", "병행수입 셀러 정보방",
    "해외직구 배대지 정보 공유", "중국 소싱 실전방", "동대문 사입 삼촌 정보방",
    "남대문 도매 상인 모임", "화곡동 도매 거래방", "온라인 셀러 세무·회계 Q&A",
    "셀러 상세페이지 품앗이", "상품 사진 촬영 정보방", "택배 계약 단가 공유방",
    "3PL 풀필먼트 정보 공유", "스마트스토어 초보 탈출방", "스마트스토어 빅파워 스터디",
    "쿠팡 초보 셀러 질문방", "오픈마켓 통합 셀러 모임", "위탁·사입 병행 셀러방",
    "무재고 셀러 스터디", "식품 온라인 판매자 모임", "건강기능식품 셀러방",
    "화장품 브랜드 창업 모임", "패션 쇼핑몰 사장님방", "여성의류 도매 거래방",
    "아동복 셀러 소통방", "반려동물 용품 셀러 모임", "인테리어 소품 판매자방",
    "캠핑용품 셀러 정보방", "핸드메이드 작가 판매 모임", "농수산물 직거래 판매자방",
    "중고 리셀러 정보 공유", "리셀·한정판 거래 정보방", "전자제품 셀러 소통방",
    "문구·팬시 셀러 모임", "공동구매 진행자 모임", "라방 셀러 소싱방",
    "유아용품 셀러 정보 공유", "크리에이터 굿즈 제작방", "구독 서비스 창업 스터디",
    # 마케팅
    "블로그 마케팅 품앗이", "인스타그램 마케팅 스터디", "유튜브 크리에이터 수익화방",
    "네이버 검색광고 실무자방", "메타 광고 운영자 모임", "구글애즈 실무 Q&A",
    "카카오모먼트 광고 스터디", "SEO 실무자 모임", "콘텐츠 마케터 네트워크",
    "그로스 해킹 스터디", "CRM 마케팅 실무방", "브랜드 마케터 소통방",
    "체험단·리뷰 마케팅 정보방", "인플루언서 협찬 정보 공유", "플레이스 마케팅 사장님방",
    "당근 비즈프로필 활용방", "라이브커머스 쇼호스트방", "이커머스 MD 모임",
    "광고 대행사 실무자 모임", "1인 마케터 생존방", "뉴스레터 운영자 모임",
    "숏폼 콘텐츠 제작자방", "제휴마케팅 수익 인증방", "쿠팡 파트너스 정보 공유",
    "애드센스 수익형 블로그방", "티스토리·워드프레스 운영자방", "퍼스널 브랜딩 스터디",
    "마케팅 툴·자동화 공유방",
    # 프리랜서
    "프리랜서 개발자 네트워크", "프리랜서 영상 편집자 모임", "프리랜서 번역가 소통방",
    "프리랜서 작가·에디터 모임", "프리랜서 마케터 일감 공유", "외주 개발 프로젝트 공유방",
    "디자인 외주 매칭방", "영상 제작 외주 정보방", "웹사이트 제작 의뢰방",
    "앱 개발 외주 정보 공유", "상세페이지 디자이너 모임", "로고·브랜딩 디자이너방",
    "UX/UI 디자이너 소통방", "일러스트레이터 작업 공유", "3D·모션그래픽 작업자방",
    "사진작가 촬영 의뢰방", "성우·나레이터 섭외방", "프리랜서 세금·계약 Q&A",
    "N잡러 부업 정보방", "재택 부업 실전방", "크몽·숨고 전문가 모임",
    "노코드 툴 사용자 모임", "워드프레스 제작자 모임", "노션 템플릿 판매자방",
    "전자책·강의 판매자 모임", "온라인 클래스 강사방",
    # 창업·자영업
    "1인 창업가 모임", "예비 창업자 스터디", "스타트업 대표 네트워크",
    "초기 스타트업 채용·구인방", "정부지원사업 정보 공유", "소상공인 정책자금 정보방",
    "사업자 대출·금융 정보방", "세무·노무 사장님 Q&A", "법인 설립·운영 정보방",
    "무인매장 창업 정보방", "프랜차이즈 창업 정보 공유", "카페 창업·운영 사장님방",
    "음식점 사장님 소통방", "배달 전문점 사장님 모임", "배민·쿠팡이츠 운영 팁",
    "베이커리·디저트 창업방", "술집·바 사장님 모임", "미용실 원장님 소통방",
    "네일·속눈썹샵 원장 모임", "피부관리실 원장님방", "헬스장·PT샵 대표 모임",
    "필라테스·요가 원장방", "학원·교습소 원장 모임", "공부방 창업 정보 공유",
    "스터디카페 점주 모임", "숙박·펜션 사장님방", "에어비앤비 호스트 모임",
    "꽃집 사장님 소통방", "인테리어 업체 대표 모임", "부동산 중개사 정보방",
    "자동차 정비·튜닝 사장님방", "세탁·수선 사장님 모임", "편의점 점주 소통방",
    "PC방·오락시설 점주방", "동네 가게 사장님 수다방", "웨딩 업체 대표 모임",
    "여행사·랜드사 실무자방", "중고차 딜러 정보방",
    # 지역
    "서울 자영업자 모임", "강남 소상공인 네트워크", "홍대·연남 사장님방",
    "성수동 브랜드 사장님 모임", "부산 온라인 셀러 모임", "대구 창업자 네트워크",
    "인천 자영업 사장님방", "광주·전남 셀러 모임", "대전·세종 창업 스터디",
    "제주 소상공인 소통방", "경기 남부 셀러 정모방", "수원·용인 자영업자방",
    # 무역·제조
    "수출입 무역 실무방", "관세·통관 정보 공유", "해외 바이어 발굴 스터디",
    "B2B 영업 담당자 모임", "제조 공장 직거래방", "OEM·ODM 제조사 매칭방",
    "패키지·박스 제작 정보방", "인쇄·판촉물 제작 의뢰방", "물류·화물 운송 정보방",
    "식자재 도매 거래방", "원단·부자재 도매 정보", "화훼·농산물 도매방",
    # 업무
    "ChatGPT 업무 활용방", "AI 이미지 제작자 모임", "데이터 분석 실무자방",
    # 맨 뒤의 여섯은 아직 승인을 기다리는 입장 요청의 이름으로 쓴다(초대 링크로만 들어가는 방).
    "엑셀·자동화 실무 팁", "쇼핑몰 CS 담당자 모임", "이커머스 개발자 모임",
    "온라인 강의 수강생 스터디", "창업 서적 독서 모임", "직장인 사이드 프로젝트방",
)  # fmt: skip
_PUBLIC_HANDLES: dict[str, str] = {
    "스마트스토어 셀러 모임": "smartstore_sellers",
    "해외구매대행 정보방": "gumaedaehaeng_info",
    "쇼핑몰 창업 스터디": "shop_startup_study",
    "퍼포먼스 마케터 모임": "performance_mkt_kr",
    "도매 사입 정보 공유": "domae_saip_info",
    "프리랜서 디자이너 네트워크": "freelance_designers_kr",
    "위탁판매 초보방": "witak_start",
    "쿠팡 로켓그로스 셀러방": "rocketgrowth_sellers",
    "아마존 셀러 코리아": "amazon_seller_korea",
    "쇼피 동남아 셀러방": "shopee_sellers_kr",
    "큐텐재팬 셀러 정보방": "qoo10jp_sellers",
    "오늘의집 입점 셀러 모임": "ohouse_seller_club",
    "인스타 마켓 운영자 모임": "insta_market_owners",
    "틱톡샵 셀러 스터디": "tiktokshop_study_kr",
    "와디즈 펀딩 메이커 모임": "funding_makers_kr",
    "자사몰 운영자 네트워크": "d2c_owners_kr",
    "카페24 쇼핑몰 운영 팁": "cafe24_tips",
    "중국 소싱 실전방": "china_sourcing_kr",
    "온라인 셀러 세무·회계 Q&A": "seller_tax_qna",
    "3PL 풀필먼트 정보 공유": "fulfillment_info_kr",
    "블로그 마케팅 품앗이": "blog_mkt_club",
    "인스타그램 마케팅 스터디": "insta_mkt_study",
    "유튜브 크리에이터 수익화방": "youtube_creators_kr",
    "네이버 검색광고 실무자방": "naver_sa_pros",
    "메타 광고 운영자 모임": "meta_ads_korea",
    "구글애즈 실무 Q&A": "googleads_qna_kr",
    "SEO 실무자 모임": "seo_korea",
    "콘텐츠 마케터 네트워크": "content_marketers_kr",
    "그로스 해킹 스터디": "growth_study_kr",
    "이커머스 MD 모임": "ecommerce_md_kr",
    "쿠팡 파트너스 정보 공유": "partners_info_kr",
    "프리랜서 개발자 네트워크": "freelance_dev_kr",
    "프리랜서 영상 편집자 모임": "video_editors_kr",
    "외주 개발 프로젝트 공유방": "dev_projects_kr",
    "UX/UI 디자이너 소통방": "uxui_designers_kr",
    "N잡러 부업 정보방": "njob_info",
    "노코드 툴 사용자 모임": "nocode_korea",
    "1인 창업가 모임": "solo_founders_kr",
    "스타트업 대표 네트워크": "startup_ceo_kr",
    "정부지원사업 정보 공유": "gov_support_info",
    "카페 창업·운영 사장님방": "cafe_owners_kr",
    "음식점 사장님 소통방": "restaurant_owners_kr",
    "에어비앤비 호스트 모임": "bnb_hosts_korea",
    "수출입 무역 실무방": "trade_practice_kr",
    "B2B 영업 담당자 모임": "b2b_sales_korea",
    "ChatGPT 업무 활용방": "chatgpt_work_kr",
    "AI 이미지 제작자 모임": "ai_image_makers",
    "데이터 분석 실무자방": "data_analysts_kr",
    "서울 자영업자 모임": "seoul_owners",
    "부산 온라인 셀러 모임": "busan_sellers",
}
"""공개 아이디가 있는 그룹. 나머지는 초대 링크로 들어간 비공개 그룹이다."""

_LEAD_NOTES: dict[LeadStatus, tuple[str, ...]] = {
    LeadStatus.REVIEWED: (
        "프로필 확인함. 스마트스토어 운영 중",
        "문의 내용이 구체적임. 이번 주 안에 연락해 보기",
        "예산이 작을 것 같음",
        "같은 그룹에서 여러 번 문의함",
    ),
    LeadStatus.CONTACTED: (
        "소개 자료 전달함. 회신 기다리는 중",
        "다음 주 화요일에 통화하기로 함",
        "단가표 요청받아서 전달함",
        "이미 다른 곳과 계약했다고 함",
        "월말 이후에 다시 이야기하기로 함",
    ),
    LeadStatus.EXCLUDED: ("동종 업계 종사자", "홍보 계정으로 보임", "관심 없다고 함"),
}

_HOUR_WEIGHTS = (
    1.2, 0.7, 0.4, 0.25, 0.2, 0.25, 0.5, 1.0, 1.8, 2.8, 3.6, 3.9,
    3.0, 3.4, 3.9, 3.8, 3.6, 3.2, 2.6, 2.4, 2.9, 3.3, 3.0, 2.1,
)  # fmt: skip
"""하루 가운데 시간대별로 글이 올라오는 정도(콘솔 시간대 기준 0시~23시)."""
_HOUR_EDGES = tuple(itertools.accumulate(_HOUR_WEIGHTS, initial=0.0))
_HIT_COUNTS = (1, 2, 3, 4, 5)
_HIT_COUNT_WEIGHTS = (42, 27, 16, 10, 5)
_INVITE_ALPHABET = string.ascii_letters + string.digits


# ---------------------------------------------------------------------------
# 계획에 쓰는 값
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Day:
    start: datetime
    """콘솔 시간대로 그날 0시."""
    span: float
    """그날 가운데 이미 지난 시간(초). 지난 날은 하루 전체다."""
    keyword: int
    activity: int
    """그날 키워드·활동량으로 처음 수집된 유저 수."""


@dataclass(eq=False)
class _GroupSeed:
    account: int
    """계정 순번(0부터)."""
    status: GroupStatus
    created_at: datetime
    joined_at: datetime | None = None
    attempted_at: datetime | None = None
    """가입을 시도한 시각."""
    first_join: bool = False
    """계정을 추가한 날 들어간 그룹. 30일 내내 감시됐다."""
    imported: bool = False
    title: str | None = None
    link_kind: LinkKind = LinkKind.INVITE
    source_link: str | None = None
    public_username: str | None = None
    invite_hash: str | None = None
    tg_chat_id: int | None = None
    kind: GroupKind | None = None
    member_count: int | None = None
    status_detail: str | None = None
    error_code: str | None = None
    messages_seen: int = 0
    last_message_at: datetime | None = None
    closed_at: datetime | None = None
    """이 시각 뒤로는 메시지를 받지 못했다(계정의 세션이 만료됨)."""
    first_leads: int = 0
    """이 그룹에서 처음 수집된 유저 수."""
    row: Group | None = None

    def use_link(self, target: LinkTarget, source_link: str | None = None) -> None:
        """이 링크로 넣은 그룹으로 만든다. source_link 는 사용자가 적어 넣은 모양이다."""
        self.link_kind = target.kind
        self.public_username = target.value if target.kind == LinkKind.PUBLIC else None
        self.invite_hash = target.value if target.kind == LinkKind.INVITE else None
        self.source_link = source_link or target.canonical_url

    def open_at(self, moment: datetime) -> bool:
        """그 시각에 이 그룹의 메시지를 받고 있었는지."""
        if self.joined_at is None or moment < self.joined_at:
            return False
        return self.closed_at is None or moment <= self.closed_at

    @property
    def group_id(self) -> int:
        if self.row is None:
            raise RuntimeError("아직 저장하지 않은 그룹이에요.")
        return self.row.id


@dataclass
class _LogSeed:
    at: datetime
    message: str
    level: LogLevel = LogLevel.INFO
    category: LogCategory = LogCategory.ACCOUNT
    account: int | None = None
    group: _GroupSeed | None = None


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def _spread(total: int, weights: Sequence[float]) -> list[int]:
    """total 을 weights 비율대로 정수로 나눈다. 합은 정확히 total 이다."""
    scale = total / sum(weights)
    shares = [weight * scale for weight in weights]
    counts = [int(share) for share in shares]
    by_remainder = sorted(range(len(shares)), key=lambda i: shares[i] - counts[i], reverse=True)
    for index in by_remainder[: total - sum(counts)]:
        counts[index] += 1
    return counts


def _weekday_factor(day: date) -> float:
    return 0.82 if day.weekday() >= 5 else 1.0


def _offset_in_day(rng: random.Random, span: float) -> float:
    """하루의 처음 span 초 안에서 고른 시각(초). 사람들이 깨어 있는 시간대에 몰린다."""
    span = max(0.0, min(span, 86_400.0))
    hour = min(int(span // 3600), 23)
    limit = _HOUR_EDGES[hour] + _HOUR_WEIGHTS[hour] * (span - hour * 3600) / 3600
    point = rng.random() * limit
    index = min(bisect_right(_HOUR_EDGES, point) - 1, 23)
    offset = index * 3600 + (point - _HOUR_EDGES[index]) / _HOUR_WEIGHTS[index] * 3600
    return max(0.0, min(offset, span - 0.001))


def _moment(rng: random.Random, day: _Day) -> datetime:
    return day.start + timedelta(seconds=_offset_in_day(rng, day.span))


def _out_of_small_hours(rng: random.Random, moment: datetime, zone: tzinfo) -> datetime:
    """새벽 1~7시에 떨어진 시각을 아침으로 민다."""
    hour = moment.astimezone(zone).hour
    if 1 <= hour < 7:
        return moment + timedelta(hours=7 - hour + rng.uniform(0.2, 3.0))
    return moment


def _wait_text(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    if not minutes:
        return f"{rest}초"
    return f"{minutes}분 {rest}초" if rest else f"{minutes}분"


def _flood_notice(seconds: int, at: datetime, zone: tzinfo) -> str:
    """엔진이 요청 제한에 걸렸을 때 남기는 기록과 같은 문장."""
    until = (at + timedelta(seconds=seconds)).astimezone(zone)
    clock = f"{until:%H:%M}"
    if until.date() != at.astimezone(zone).date():
        clock = f"{until.month}월 {until.day}일 {clock}"
    return (
        f"텔레그램이 요청을 잠시 제한했어요. {_wait_text(seconds)} 뒤({clock})에 이어서 진행해요."
    )


def _invite_hash(rng: random.Random) -> str:
    return "".join(rng.choice(_INVITE_ALPHABET) for _ in range(16))


def _target_of(group: Group) -> LinkTarget | None:
    """그룹 행의 링크로 가입 대상을 만든다. 링크가 없으면 None."""
    if group.link_kind == LinkKind.INVITE:
        return LinkTarget(LinkKind.INVITE, group.invite_hash) if group.invite_hash else None
    if group.public_username:
        return LinkTarget(LinkKind.PUBLIC, group.public_username)
    return None


# ---------------------------------------------------------------------------
# 날짜별 계획
# ---------------------------------------------------------------------------


def _plan_days(rng: random.Random, zone: tzinfo, now: datetime) -> list[_Day]:
    """지난 30일(오늘 포함)의 날마다 새로 수집될 유저 수를 정한다.

    최근 7일은 정해 둔 값을 그대로 쓴다. 그 앞은 처음 감시를 시작했을 때 많이 수집되다가
    차츰 줄어드는 모양이다(이미 수집된 사람이 다시 걸리는 일이 늘어서).
    """
    today = now.astimezone(zone).date()
    dates = [today - timedelta(days=HISTORY_DAYS - 1 - i) for i in range(HISTORY_DAYS)]
    older = HISTORY_DAYS - len(RECENT_KEYWORD_LEADS)
    keyword_total = sum(spec.leads for spec in _RULES if spec.kind == RuleKind.KEYWORD)
    activity_total = TOTAL_LEADS - keyword_total
    keyword = _spread(
        keyword_total - sum(RECENT_KEYWORD_LEADS),
        [
            (80 + 170 * math.exp(-i / 6.5)) * _weekday_factor(dates[i]) * rng.uniform(0.9, 1.1)
            for i in range(older)
        ],
    )
    activity = _spread(
        activity_total - sum(RECENT_ACTIVITY_LEADS),
        [_weekday_factor(dates[i]) * rng.uniform(0.85, 1.15) for i in range(older)],
    )
    days: list[_Day] = []
    for day, keyword_leads, activity_leads in zip(
        dates,
        (*keyword, *RECENT_KEYWORD_LEADS),
        (*activity, *RECENT_ACTIVITY_LEADS),
        strict=True,
    ):
        start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
        span = (min(end, now) - start).total_seconds()
        days.append(_Day(start, span, keyword_leads, activity_leads))
    return days


# ---------------------------------------------------------------------------
# 그룹과 활동 기록
# ---------------------------------------------------------------------------


class _Story:
    """그동안 있었던 일. 그룹과, 최근 며칠의 활동 기록을 함께 적어 나간다."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.groups: list[_GroupSeed] = []
        self.logs: list[_LogSeed] = []

    def ago(self, hours: float = 0.0, *, minutes: float = 0.0, seconds: float = 0.0) -> datetime:
        return self.now - timedelta(hours=hours, minutes=minutes, seconds=seconds)

    def log(
        self,
        at: datetime,
        message: str,
        *,
        level: LogLevel = LogLevel.INFO,
        category: LogCategory = LogCategory.ACCOUNT,
        account: int | None = None,
        group: _GroupSeed | None = None,
    ) -> None:
        self.logs.append(_LogSeed(at, message, level, category, account, group))

    def group_log(self, group: _GroupSeed, at: datetime, message: str, **extra: Any) -> None:
        self.log(
            at, message, category=LogCategory.GROUP, account=group.account, group=group, **extra
        )

    def joined(
        self,
        account: int,
        created_at: datetime,
        joined_at: datetime,
        *,
        first_join: bool = False,
        imported: bool = False,
        announce: bool = True,
    ) -> _GroupSeed:
        group = _GroupSeed(
            account=account,
            status=GroupStatus.JOINED,
            created_at=created_at,
            joined_at=joined_at,
            attempted_at=None if imported else joined_at,
            first_join=first_join,
            imported=imported,
        )
        self.groups.append(group)
        if announce and not first_join and not imported:
            self.group_log(group, joined_at, _LOG_JOINED)
        return group

    def requested(self, account: int, created_at: datetime, at: datetime, link: LinkTarget) -> None:
        group = _GroupSeed(
            account=account,
            status=GroupStatus.REQUESTED,
            created_at=created_at,
            attempted_at=at,
            status_detail=_DETAIL_REQUESTED,
        )
        group.use_link(link)
        self.groups.append(group)
        self.group_log(group, at, _LOG_REQUESTED)

    def failed(
        self,
        account: int,
        created_at: datetime,
        at: datetime,
        link: LinkTarget,
        code: str,
        reason: str,
    ) -> None:
        group = _GroupSeed(
            account=account,
            status=GroupStatus.FAILED,
            created_at=created_at,
            attempted_at=at,
            error_code=code,
            status_detail=reason,
        )
        group.use_link(link)
        self.groups.append(group)
        self.group_log(group, at, f"{_LOG_JOIN_FAILED} {reason}", level=LogLevel.WARNING)

    def queued(
        self, account: int, created_at: datetime, link: LinkTarget, source_link: str | None = None
    ) -> None:
        group = _GroupSeed(account=account, status=GroupStatus.QUEUED, created_at=created_at)
        group.use_link(link, source_link)
        self.groups.append(group)

    def queue_notice(self, at: datetime, count: int, account: int | None = None) -> None:
        self.log(
            at,
            f"그룹 {count}개를 가입 대기열에 넣었어요.",
            category=LogCategory.GROUP,
            account=account,
        )


def _tell_story(rng: random.Random, now: datetime, setup_at: datetime, zone: tzinfo) -> _Story:
    """계정을 추가한 날부터 지금까지의 일을 적는다. 모든 시각은 now 보다 앞이다."""
    story = _Story(now)
    ago = story.ago

    # 계정을 추가한 날: 계정마다 링크를 한꺼번에 넣었고, 가입 간격을 지키며 하나씩 들어갔다.
    for index, spec in enumerate(_ACCOUNTS):
        created_at = _account_created_at(setup_at, index) + timedelta(minutes=3)
        joined_at = created_at
        for _ in range(spec.first_joins):
            joined_at += timedelta(seconds=rng.uniform(92, 125))
            story.joined(index, created_at, joined_at, first_join=True)

    # 나흘 전: 지우 계정의 입장 요청 하나. 이틀 뒤에 승인됐다.
    approved = story.joined(0, ago(96), ago(47.5), announce=False)
    story.group_log(approved, ago(96, seconds=-3), _LOG_REQUESTED)
    story.group_log(approved, ago(47.5), _LOG_APPROVED)

    # 사흘 전: 서버를 다시 켰다.
    for index in range(len(_ACCOUNTS)):
        story.log(ago(74, seconds=-0.7 * index), _LOG_CONNECTED, account=index)

    # 수아 계정이 원래 들어가 있던 그룹을 불러왔다.
    imports = _ACCOUNTS[8].joined - _ACCOUNTS[8].first_joins
    for _ in range(imports):
        story.joined(8, ago(73.5), ago(73.5), imported=True)
    story.log(
        ago(73.5),
        f"이미 들어가 있던 그룹 {imports}개를 감시 목록에 넣었어요.",
        category=LogCategory.GROUP,
        account=8,
    )

    # 그 뒤로 링크를 몇 번 더 넣었다.
    story.queue_notice(ago(71), 4)
    for account, seconds in ((1, 6), (3, 9), (5, 13), (6, 17)):
        story.joined(account, ago(71), ago(71, seconds=-seconds))

    story.queue_notice(ago(49), 3, account=4)
    story.joined(4, ago(49), ago(49, seconds=-5))
    story.joined(4, ago(49), ago(49, seconds=-101))
    story.requested(4, ago(49), ago(49, seconds=-197), _REQUEST_LINKS[0])

    story.queue_notice(ago(27.5), 5)
    story.joined(7, ago(27.5), ago(27.5, seconds=-4))
    story.joined(2, ago(27.5), ago(27.5, seconds=-6))
    story.requested(7, ago(27.5), ago(27.5, seconds=-98), _REQUEST_LINKS[1])
    story.requested(2, ago(27.5), ago(27.5, seconds=-101), _REQUEST_LINKS[2])
    story.joined(7, ago(27.5), ago(27.5, seconds=-192))

    # 건우 계정: 링크 일곱 개를 처리하던 중에 세션이 만료됐다. 두 개는 대기열에 남았다.
    expired_at = _session_expired_at(now)
    queued_at = expired_at - timedelta(minutes=9.5)

    def then(minutes: float) -> datetime:
        return queued_at + timedelta(minutes=minutes)

    story.queue_notice(queued_at, 7, account=_EXPIRED)
    story.requested(_EXPIRED, queued_at, then(0.5), _REQUEST_LINKS[3])
    story.failed(
        _EXPIRED, queued_at, then(2.2), _EXPIRED_LINK, "invite_expired", _MSG_INVITE_EXPIRED
    )
    story.requested(_EXPIRED, queued_at, then(3.9), _REQUEST_LINKS[4])
    story.failed(_EXPIRED, queued_at, then(5.6), _PRIVATE_LINK, "private", _MSG_PRIVATE)
    story.requested(_EXPIRED, queued_at, then(7.3), _REQUEST_LINKS[5])
    story.queued(_EXPIRED, queued_at, _QUEUED_PUBLIC_LINK, f"@{_QUEUED_PUBLIC_LINK.value}")
    story.queued(_EXPIRED, queued_at, _QUEUED_INVITE_LINK)
    story.log(expired_at, _MSG_SESSION_EXPIRED, level=LogLevel.ERROR, account=_EXPIRED)

    # 어제: 태양 계정이 가입하다가 잠깐 요청 제한에 걸렸다.
    story.queue_notice(ago(22), 2, account=3)
    story.joined(3, ago(22), ago(22, seconds=-5))
    limited_at = ago(22, seconds=-97)
    story.log(limited_at, _flood_notice(252, limited_at, zone), level=LogLevel.WARNING, account=3)
    story.log(limited_at + timedelta(seconds=253), _LOG_FLOOD_LIFTED, account=3)
    story.joined(3, ago(22), limited_at + timedelta(seconds=254))

    story.queue_notice(ago(5.2), 2)
    story.joined(5, ago(5.2), ago(5.2, seconds=-4))
    story.joined(1, ago(5.2), ago(5.2, seconds=-8))

    # 가끔 연결이 끊겼다가 바로 다시 붙었다.
    for account, hours in (
        (8, 66.3), (1, 58.9), (7, 41.2), (0, 33.7), (6, 19.4), (5, 12.6), (4, 8.1), (2, 2.3),
    ):  # fmt: skip
        story.log(ago(hours), _LOG_DISCONNECTED, level=LogLevel.WARNING, account=account)
        story.log(ago(hours, seconds=-rng.uniform(6, 14)), _LOG_CONNECTED, account=account)

    # 방금: 예린 계정이 요청 제한에 걸렸다.
    limited_at = ago(minutes=1)
    story.log(
        limited_at,
        _flood_notice((FLOOD_WAIT_MINUTES + 1) * 60, limited_at, zone),
        level=LogLevel.WARNING,
        account=_FLOODED,
    )
    return story


def _account_created_at(setup_at: datetime, index: int) -> datetime:
    return setup_at + timedelta(minutes=55 * index)


def _session_expired_at(now: datetime) -> datetime:
    return now - timedelta(hours=26)


def _dress_groups(rng: random.Random, groups: list[_GroupSeed], now: datetime) -> list[_GroupSeed]:
    """그룹마다 이름·링크·인원·메시지 수를 붙인다. 가입된 그룹을 많이 수집되는 순서로 돌려준다."""
    joined = [group for group in groups if group.status == GroupStatus.JOINED]
    pending = [group for group in groups if group.status == GroupStatus.REQUESTED]
    top = len(_TOP_GROUP_LEADS)

    # 이름난 그룹은 30일 내내 감시된 그룹 가운데 계정 순서대로 하나씩 맡긴다.
    ranked: list[_GroupSeed] = []
    for account in range(top):
        ranked.append(next(g for g in joined if g.account == account and g.first_join))
    rest = [group for group in joined if group not in ranked]
    rng.shuffle(rest)
    ranked += rest

    weights = [(rank + 3) ** -0.75 * rng.uniform(0.7, 1.3) for rank in range(top, len(ranked))]
    quotas = (*_TOP_GROUP_LEADS, *_spread(TOTAL_LEADS - sum(_TOP_GROUP_LEADS), weights))
    heaviest = max(weights)
    chat_numbers = rng.sample(range(1_200_000_000, 2_400_000_000), len(ranked))
    for rank, group in enumerate(ranked):
        group.title = _GROUP_TITLES[rank]
        group.first_leads = quotas[rank]
        group.kind = GroupKind.SUPERGROUP
        group.tg_chat_id = -(1_000_000_000_000 + chat_numbers[rank])
        if rank < top:
            group.member_count = _TOP_GROUP_MEMBERS[rank]
        elif rank >= len(ranked) - 14:
            # 아주 작은 방은 슈퍼그룹이 아닌 일반 그룹이다.
            group.kind = GroupKind.GROUP
            group.member_count = rng.randint(48, 196)
            group.tg_chat_id = -(4_000_000_000 + chat_numbers[rank] % 900_000_000)
        else:
            share = weights[rank - top] / heaviest
            group.member_count = round(260 + 3_300 * share**1.3 * rng.uniform(0.8, 1.3))
        _attach_link(rng, group)
        if group.account == _EXPIRED:
            group.closed_at = _session_expired_at(now)
        _count_messages(rng, group, now)

    for group, title in zip(pending, _GROUP_TITLES[-len(pending) :], strict=True):
        group.title = title
        group.member_count = round(180 * 30 ** rng.random())
    return ranked


def _attach_link(rng: random.Random, group: _GroupSeed) -> None:
    handle = _PUBLIC_HANDLES.get(group.title or "")
    if group.imported:
        group.link_kind = LinkKind.EXISTING
        group.public_username = handle
    elif handle is not None:
        # 공개 그룹은 사람마다 적는 모양이 다르다.
        typed = rng.choice((None, None, f"t.me/{handle}", f"@{handle}"))
        group.use_link(LinkTarget(LinkKind.PUBLIC, handle), typed)
    else:
        group.use_link(LinkTarget(LinkKind.INVITE, _invite_hash(rng)))


def _count_messages(rng: random.Random, group: _GroupSeed, now: datetime) -> None:
    """감시한 기간과 인원에 맞는 메시지 수와, 마지막 메시지 시각을 정한다."""
    if group.joined_at is None or group.member_count is None:
        return
    until = group.closed_at or now
    per_day = 0.9 * group.member_count**0.75
    watched = max(0.0, (until - group.joined_at).total_seconds())
    group.messages_seen = round(per_day * watched / 86_400 * rng.uniform(0.8, 1.2))
    if group.messages_seen:
        quiet = min(watched, 6 * 3600, rng.expovariate(per_day / 86_400 / 3))
        group.last_message_at = until - timedelta(seconds=quiet)


# ---------------------------------------------------------------------------
# 수집된 유저와 감지 기록
# ---------------------------------------------------------------------------


def _pick_lead_users(rng: random.Random) -> tuple[list[TgUser], TgUser]:
    """수집된 유저가 될 사람들과, 제외 목록에 올릴 사람 하나."""
    people = demo_population(_POPULATION)
    speakers = [user for user in people[:POOL_SIZE] if user.username and not user.is_bot]
    silent = [user for user in people[POOL_SIZE:] if user.username and not user.is_bot]
    known = rng.sample(speakers, round(len(speakers) * _POOL_LEAD_SHARE))
    known_ids = {user.id for user in known}
    blocked = next(user for user in speakers if user.id not in known_ids)
    users = known + silent[: TOTAL_LEADS - len(known)]
    if len(users) != TOTAL_LEADS:
        raise RuntimeError("데모 유저가 모자라요. _POPULATION 을 늘려 주세요.")
    rng.shuffle(users)
    return users, blocked


def _excerpts(
    rng: random.Random, spec: _RuleSpec, others: Sequence[_RuleSpec]
) -> list[tuple[str, list[str]]]:
    """이 규칙에만 걸리는 글의 (발췌, 걸린 키워드) 묶음."""
    if spec.intent is None:
        return []
    found: dict[str, list[str]] = {}
    for _ in range(900):
        text = intent_message(rng, spec.intent)
        if text in found:
            continue
        matched = match_keywords(text, list(spec.keywords))
        if matched and not any(match_keywords(text, list(other.keywords)) for other in others):
            found[text] = matched
    return [(make_excerpt(text, matched), matched) for text, matched in found.items()]


def _lead_status(rng: random.Random, age_days: float) -> LeadStatus:
    """오래된 유저일수록 이미 확인했거나 연락해 본 경우가 많다."""
    if age_days < 1:
        shares = (97, 3, 0, 0)
    elif age_days < 3:
        shares = (84, 11, 4, 1)
    elif age_days < 10:
        shares = (75, 16, 8, 1)
    else:
        shares = (65, 21, 12, 2)
    statuses = (LeadStatus.NEW, LeadStatus.REVIEWED, LeadStatus.CONTACTED, LeadStatus.EXCLUDED)
    return rng.choices(statuses, weights=shares)[0]


def _next_hit_gap(rng: random.Random, *, activity: bool) -> timedelta:
    """같은 유저가 다시 감지되기까지의 간격. 활동량 감지는 기간(24시간)이 지나야 다시 기록된다."""
    if activity:
        return timedelta(hours=rng.uniform(24.5, 80))
    if rng.random() < 0.35:
        return timedelta(minutes=rng.uniform(20, 360))
    return timedelta(days=rng.uniform(0.6, 9.0))


def _plan_history(
    rng: random.Random,
    days: Sequence[_Day],
    ranked: Sequence[_GroupSeed],
    rules: Sequence[Rule],
    account_ids: Sequence[int],
    users: Sequence[TgUser],
    now: datetime,
    zone: tzinfo,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """수집된 유저와 감지 기록의 행을 만든다(유저는 처음 수집된 순, 감지는 시간순).

    감지 행의 "tg_user_id" 는 유저를 찾는 키다. 저장하기 전에 lead_id 로 바꾼다.
    """
    keyword_specs = [spec for spec in _RULES if spec.kind == RuleKind.KEYWORD]
    excerpts = [
        _excerpts(rng, spec, [other for other in keyword_specs if other is not spec])
        for spec in _RULES
    ]
    rule_weights = [spec.leads for spec in _RULES]

    # 날마다 정해 둔 수만큼의 자리. 키워드 자리는 규칙별 인원에 맞춰 나눈다.
    keyword_rules = [
        index
        for index, spec in enumerate(_RULES)
        if spec.kind == RuleKind.KEYWORD
        for _ in range(spec.leads)
    ]
    rng.shuffle(keyword_rules)
    slots: list[tuple[_Day, int]] = []
    for day in days:
        slots += [(day, keyword_rules.pop()) for _ in range(day.keyword)]
        slots += [(day, _ACTIVITY_RULE)] * day.activity

    first_groups = [group for group in ranked for _ in range(group.first_leads)]
    rng.shuffle(first_groups)
    popularity = list(itertools.accumulate(group.first_leads for group in ranked))

    def pick_group(moment: datetime) -> _GroupSeed:
        for _ in range(12):
            group = rng.choices(ranked, cum_weights=popularity)[0]
            if group.open_at(moment):
                return group
        return ranked[0]  # 맨 앞 그룹은 30일 내내 열려 있었다

    def hit_row(user: TgUser, moment: datetime, rule: int, group: _GroupSeed) -> dict[str, Any]:
        spec = _RULES[rule]
        row: dict[str, Any] = {
            "tg_user_id": user.id,
            "rule_id": rules[rule].id,
            "group_id": group.group_id,
            "account_id": account_ids[group.account],
            "kind": spec.kind,
            "rule_name": spec.name,
            "group_title": group.title,
            "keywords": [],
            "excerpt": None,
            "tg_message_id": None,
            "message_count": None,
            "window_hours": None,
            "created_at": moment,
        }
        if spec.kind == RuleKind.ACTIVITY:
            row["message_count"] = (spec.min_messages or 0) + min(55, int(rng.expovariate(1 / 8)))
            row["window_hours"] = spec.window_hours
        else:
            row["excerpt"], row["keywords"] = rng.choice(excerpts[rule])
            row["tg_message_id"] = rng.randrange(1_200, 480_000)
        return row

    leads: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    for (day, first_rule), first_group, user in zip(slots, first_groups, users, strict=True):
        moment = min(_moment(rng, day), now)
        group = first_group if first_group.open_at(moment) else pick_group(moment)
        trail = [hit_row(user, moment, first_rule, group)]
        for _ in range(rng.choices(_HIT_COUNTS, weights=_HIT_COUNT_WEIGHTS)[0] - 1):
            rule = first_rule
            if rng.random() < _CROSS_RULE_SHARE:
                rule = rng.choices(range(len(_RULES)), weights=rule_weights)[0]
            gap = _next_hit_gap(rng, activity=_RULES[rule].kind == RuleKind.ACTIVITY)
            moment = _out_of_small_hours(rng, moment + gap, zone)
            if moment > now:
                break
            if rng.random() >= _SAME_GROUP_SHARE or not group.open_at(moment):
                group = pick_group(moment)
            trail.append(hit_row(user, moment, rule, group))

        status = _lead_status(rng, (now - trail[0]["created_at"]).total_seconds() / 86_400)
        notes = _LEAD_NOTES.get(status)
        leads.append(
            {
                "tg_user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "status": status,
                "note": rng.choice(notes) if notes and rng.random() < 0.4 else None,
                "hit_count": len(trail),
                "first_kind": _RULES[first_rule].kind,
                "first_seen_at": trail[0]["created_at"],
                "last_seen_at": trail[-1]["created_at"],
                "last_hit_id": None,
            }
        )
        hits += trail

    leads.sort(key=lambda row: row["first_seen_at"])
    hits.sort(key=lambda row: row["created_at"])
    return leads, hits


def _plan_buckets(
    rng: random.Random,
    ranked: Sequence[_GroupSeed],
    hits: Sequence[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """말이 많은 사람들의 지난 24시간 메시지 수. 기준에 조금 못 미치게 넣어 둔다.

    켜 두면 이 사람들이 몇 마디 더 하는 대로 활동량 규칙에 걸린다.
    """
    activity = _RULES[_ACTIVITY_RULE]
    threshold = activity.min_messages or 0
    window = timedelta(hours=activity.window_hours or 0)
    already = {
        (hit["group_id"], hit["tg_user_id"])
        for hit in hits
        if hit["kind"] == RuleKind.ACTIVITY and hit["created_at"] > now - window
    }
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    rows: list[dict[str, Any]] = []
    for group in ranked:
        if group.closed_at is not None or group.tg_chat_id is None or group.joined_at is None:
            continue
        for user in demo_chat_cast(group.tg_chat_id).chatty:
            if (group.group_id, user.id) in already or rng.random() < 0.5:
                continue
            hours = [
                this_hour - timedelta(hours=back)
                for back in rng.sample(range(19), rng.randint(2, 5))
            ]
            hours = [hour for hour in hours if hour >= group.joined_at]
            if not hours:
                continue
            total = rng.randint(threshold * 2 // 5, threshold - 1)
            counts = _spread(total, [rng.uniform(0.5, 1.5) for _ in hours])
            rows += [
                {"group_id": group.group_id, "tg_user_id": user.id, "hour": hour, "count": count}
                for hour, count in zip(hours, counts, strict=True)
                if count
            ]
    return rows


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------


def _account_rows(story: _Story, secrets: Secrets, setup_at: datetime) -> list[Account]:
    now = story.now
    rows: list[Account] = []
    for index, spec in enumerate(_ACCOUNTS):
        connected = [
            log.at for log in story.logs if log.account == index and log.message == _LOG_CONNECTED
        ]
        attempts = [
            group.attempted_at
            for group in story.groups
            if group.account == index and group.attempted_at is not None
        ]
        account = Account(
            phone=spec.phone,
            tg_user_id=spec.tg_user_id,
            first_name=spec.name,
            username=spec.username,
            session_enc=secrets.encrypt(f"{SESSION_PREFIX}{index + 1}"),
            enabled=True,
            status=AccountStatus.OFFLINE,
            last_join_at=max(attempts, default=None),
            last_connected_at=max(connected, default=None),
            created_at=_account_created_at(setup_at, index),
        )
        if index == _FLOODED:
            account.status = AccountStatus.FLOOD_WAIT
            account.status_detail = _DETAIL_FLOOD
            account.flood_until = now + timedelta(minutes=FLOOD_WAIT_MINUTES)
        elif index == _EXPIRED:
            account.status = AccountStatus.REAUTH_REQUIRED
            account.status_detail = _MSG_SESSION_EXPIRED
        rows.append(account)
    return rows


def _group_row(group: _GroupSeed, account_id: int) -> Group:
    return Group(
        account_id=account_id,
        source_link=group.source_link,
        link_kind=group.link_kind,
        public_username=group.public_username,
        invite_hash=group.invite_hash,
        tg_chat_id=group.tg_chat_id,
        title=group.title,
        kind=group.kind,
        member_count=group.member_count,
        status=group.status,
        status_detail=group.status_detail,
        error_code=group.error_code,
        attempts=0,
        monitoring=True,
        messages_seen=group.messages_seen,
        last_message_at=group.last_message_at,
        joined_at=group.joined_at,
        created_at=group.created_at,
    )


def _rule_rows(setup_at: datetime) -> list[Rule]:
    return [
        Rule(
            name=spec.name,
            kind=spec.kind,
            enabled=True,
            keywords=list(spec.keywords),
            exclude_keywords=[],
            min_messages=spec.min_messages,
            window_hours=spec.window_hours,
            all_groups=True,
            created_at=setup_at + timedelta(minutes=5 + 2 * index),
            updated_at=setup_at + timedelta(minutes=5 + 2 * index),
        )
        for index, spec in enumerate(_RULES)
    ]


async def _seed(session: AsyncSession, secrets: Secrets, zone: tzinfo, now: datetime) -> None:
    """30일치 기록을 한 트랜잭션에 채운다(커밋은 부른 쪽이 한다)."""
    rng = random.Random(_SEED)
    days = _plan_days(rng, zone, now)
    setup_at = days[0].start - timedelta(hours=13)
    story = _tell_story(rng, now, setup_at, zone)
    ranked = _dress_groups(rng, story.groups, now)

    accounts = _account_rows(story, secrets, setup_at)
    rules = _rule_rows(setup_at)
    session.add_all([*accounts, *rules])
    await session.flush()
    account_ids = [account.id for account in accounts]

    for group in sorted(story.groups, key=lambda group: group.created_at):
        group.row = _group_row(group, account_ids[group.account])
        session.add(group.row)
    await session.flush()

    users, blocked = _pick_lead_users(rng)
    leads, hits = _plan_history(rng, days, ranked, rules, account_ids, users, now, zone)
    buckets = _plan_buckets(rng, ranked, hits, now)

    # 행이 많은 표는 ORM 객체를 거치지 않고 한 문장으로 넣는다.
    connection = await session.connection()
    await connection.execute(insert(Lead.__table__), leads)
    lead_ids = {
        tg_user_id: lead_id
        for tg_user_id, lead_id in await session.execute(select(Lead.tg_user_id, Lead.id))
    }
    for hit in hits:
        hit["lead_id"] = lead_ids[hit.pop("tg_user_id")]
    await connection.execute(insert(Hit.__table__), hits)
    latest_hit = (
        select(Hit.id)
        .where(Hit.lead_id == Lead.id)
        .order_by(Hit.created_at.desc(), Hit.id.desc())
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )
    await session.execute(
        update(Lead).values(last_hit_id=latest_hit),
        execution_options={"synchronize_session": False},
    )
    if buckets:
        await connection.execute(insert(ActivityBucket.__table__), buckets)

    # 감지가 있었던 그룹은 그 뒤에 메시지가 없었을 수 없다.
    latest_by_group: dict[int, datetime] = {}
    for hit in hits:
        latest_by_group[hit["group_id"]] = hit["created_at"]
    for group in ranked:
        latest = latest_by_group.get(group.group_id)
        if group.row is not None and latest is not None:
            if group.row.last_message_at is None or group.row.last_message_at < latest:
                group.row.last_message_at = latest

    session.add_all(
        EventLog(
            level=log.level,
            category=log.category,
            message=log.message,
            account_id=account_ids[log.account] if log.account is not None else None,
            group_id=log.group.group_id if log.group is not None else None,
            created_at=log.at,
        )
        for log in sorted(story.logs, key=lambda log: log.at)
    )
    session.add_all(
        [
            BlocklistEntry(
                username="coin_signal_vip",
                note="코인 리딩방 홍보 계정",
                created_at=now - timedelta(days=12, hours=3),
            ),
            BlocklistEntry(
                username="event_promo_kr",
                note="이벤트 홍보만 올리는 계정",
                created_at=now - timedelta(days=6, hours=7),
            ),
            BlocklistEntry(
                username=(blocked.username or "").lower(),
                note="경쟁사 직원",
                created_at=now - timedelta(days=2, hours=5),
            ),
        ]
    )


# ---------------------------------------------------------------------------
# 게이트웨이의 세계 채우기
# ---------------------------------------------------------------------------


def _chat_of(group: Group, target: LinkTarget | None) -> TgChat:
    """그룹 행이 가리키는 방. 아직 방 정보를 모르면 링크로 정해지는 방의 것으로 채운다."""
    planned = demo_join_plan(target).chat if target is not None else None
    chat_id = group.tg_chat_id or (planned.id if planned is not None else None)
    if chat_id is None:
        raise ValueError("방을 알 수 없는 그룹이에요.")
    return TgChat(
        id=chat_id,
        title=group.title or (planned.title if planned is not None else f"그룹 {group.id}"),
        username=group.public_username,
        kind=GroupKind(group.kind) if group.kind else GroupKind.SUPERGROUP,
        member_count=group.member_count
        if group.member_count is not None
        else (planned.member_count if planned is not None else None),
    )


async def _sync_world(
    session: AsyncSession, gateway: DemoGateway, secrets: Secrets, now: datetime
) -> None:
    """DB 의 계정·그룹을 게이트웨이의 세계에 올리고, 계정별로 정해 둔 상황을 다시 건다."""
    accounts = (await session.scalars(select(Account).order_by(Account.id))).all()
    for account in accounts:
        session_text = secrets.decrypt(account.session_enc) if account.session_enc else None
        if (
            session_text is not None
            and session_text.startswith(SESSION_PREFIX)
            and account.tg_user_id is not None
        ):
            gateway.register_session(
                session_text,
                TgUser(
                    id=account.tg_user_id,
                    username=account.username,
                    first_name=account.first_name,
                    last_name=account.last_name,
                    phone=account.phone,
                ),
            )
        if account.flood_until is not None and account.flood_until > now:
            gateway.start_flood_wait(account.id, account.flood_until)
        seeded = _SEEDED_USER_IDS.get(account.tg_user_id or 0)
        if seeded is not None:
            for step in (0, 3, 5):
                gateway.register_chat(
                    account.id, _EXTRA_DIALOGS[(seeded + step) % len(_EXTRA_DIALOGS)]
                )
    gateway.revoke_session(EXPIRED_SESSION)

    groups = await session.scalars(
        select(Group)
        .where(Group.status.in_((GroupStatus.JOINED, GroupStatus.REQUESTED)))
        .order_by(Group.id)
    )
    for group in groups:
        target = _target_of(group)
        if group.status == GroupStatus.JOINED:
            if group.tg_chat_id is not None:
                gateway.register_chat(group.account_id, _chat_of(group, target), target=target)
        elif target is not None:
            gateway.register_request(
                group.account_id,
                target,
                _chat_of(group, target),
                approve=target.value not in HELD_REQUESTS,
            )


async def _has_other_data(session: AsyncSession) -> bool:
    for model in (Lead, Hit, Rule, Group):
        if await session.scalar(select(model.id).limit(1)) is not None:
            return True
    return False


async def ensure_demo_data(ctx: AppContext, *, now: datetime | None = None) -> None:
    """데모 데이터를 준비한다. 엔진을 켜기 전에 한 번 부른다.

    계정이 하나도 없으면 30일치 기록을 채운다(다시 불러도 두 번 채우지 않는다). 계정이 있든
    없든, DB 의 계정·그룹을 데모 게이트웨이에 올려서 대화가 흐르게 한다.
    now 는 기록의 기준 시각이다(테스트용).
    """
    moment = now or utcnow()
    zone = (await ctx.settings.get()).tzinfo
    gateway = ctx.engine.gateway
    seeded = False
    async with ctx.db.session() as session:
        if await session.scalar(select(Account.id).limit(1)) is None:
            if await _has_other_data(session):
                logger.warning(
                    "계정은 없는데 다른 데이터가 남아 있어서 데모 데이터를 채우지 않았어요. "
                    "처음 상태로 되돌리려면 데이터 폴더를 비우고 다시 시작해 주세요."
                )
            else:
                await _seed(session, ctx.secrets, zone, moment)
                await session.commit()
                seeded = True
        if isinstance(gateway, DemoGateway):
            await _sync_world(session, gateway, ctx.secrets, moment)
        else:
            logger.warning("데모 게이트웨이가 아니어서 데모 그룹의 대화는 만들지 않아요.")
    if seeded:
        ctx.collector.invalidate()  # 규칙·제외 목록·내 계정이 새로 생겼다
        logger.info("데모 데이터를 채웠어요.")
