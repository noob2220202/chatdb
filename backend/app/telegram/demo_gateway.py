"""데모 게이트웨이: 텔레그램에 접속하지 않고, 그럴듯한 그룹 대화가 흐르는 가짜 세계를 만든다.

엔진과 수집기는 실제와 똑같이 돈다. 이 파일은 듣는 쪽(들어오는 메시지, 그룹 가입, 로그인)만
흉내 내고, 어디로도 메시지를 보내지 않는다.

    gateway = DemoGateway(pace=(0.02, 0.05), seed=7)        # 테스트: 빠르게, 같은 순서로
    gateway.register_session("demo:1", user)                 # 이 세션으로 접속하면 이 사람이다
    gateway.register_chat(account_id, chat, target=target)   # 이미 들어가 있는 그룹
    gateway.register_request(account_id, target, chat)       # 승인을 기다리는 입장 요청
    gateway.revoke_session("demo:10")                        # 이 세션은 만료됐다
    gateway.start_flood_wait(account_id, until)              # 이 계정은 until 까지 요청 제한이다

세계(사람들, 그룹 구성원, 링크별 가입 결과)는 언제 만들어도 같다. 그래서 다시 켜도 같은 사람이
같은 아이디로 말한다. 무작위인 것은 누가 언제 무슨 말을 하느냐뿐이고, seed 로 고정할 수 있다.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import logging
import math
import random
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from functools import lru_cache

from ..db import utcnow
from ..links import LinkTarget
from ..models import GroupKind, LinkKind
from .gateway import (
    AccountClient,
    IncomingMessage,
    JoinOutcome,
    JoinResult,
    LoginResult,
    MessageHandler,
    PendingLogin,
    TelegramError,
    TelegramGateway,
    TgChat,
    TgErrorCode,
    TgUser,
)

logger = logging.getLogger("chatdb.demo")

Clock = Callable[[], datetime]

SESSION_PREFIX = "demo:"
DEMO_CODE = "12345"
DEMO_PASSWORD = "demo"
TWO_FACTOR_PHONE_SUFFIX = "0000"
"""이 숫자로 끝나는 번호는 2단계 인증 비밀번호를 묻는다."""
LOGIN_TTL = timedelta(minutes=10)

POOL_SIZE = 400
"""그룹에서 말하는 사람 수. 이 가운데 아이디가 없는 사람과 봇은 수집되지 않는다."""
INTENT_RATIO = 0.15
"""메시지 가운데 견적·업체 추천·대행 문의처럼 살 뜻이 보이는 글의 비율."""

_WORLD_SEED = "chatdb-demo-world-1"
_NO_USERNAME_SHARE = 0.2
_BOT_SHARE = 0.02
_ANONYMOUS_SHARE = 0.01
"""익명 관리자 명의로 올라오는 글(발신자 없음)의 비율."""
_MIXED_INTENT_SHARE = 0.08
_FIXED_INTENT_SHARE = 0.3
_CHATTY_PER_CHAT = 2
_CHATTY_WEIGHT = 9.0
_BOT_WEIGHT = 0.5

_MSG_SESSION_EXPIRED = "세션이 만료됐어요. 다시 로그인해 주세요."
_MSG_SESSION_CLOSED = "다른 기기에서 이 세션을 종료했어요. 다시 로그인해 주세요."
_MSG_REAL_SESSION = (
    "데모 모드에서는 실제 텔레그램 세션을 쓸 수 없어요. 데모 계정으로 다시 로그인해 주세요."
)
_MSG_SESSION_FORMAT = (
    f"세션을 읽을 수 없어요. 데모 모드에서는 {SESSION_PREFIX} 로 시작하는 세션만 불러올 수 있어요."
)
_MSG_NOT_CONNECTED = "텔레그램에 연결돼 있지 않아요. 잠시 뒤에 다시 시도해 주세요."
_MSG_LOGIN_EXPIRED = "로그인 절차가 만료됐어요. 처음부터 다시 시도해 주세요."


# ---------------------------------------------------------------------------
# 말뭉치
# ---------------------------------------------------------------------------

CHATTER: tuple[str, ...] = (
    "오늘 택배 마감 몇 시까지예요?",
    "스마트스토어 정산 주기 바뀐 거 보셨어요?",
    "이번 달 매출이 반토막 났네요 ㅠㅠ",
    "쿠팡 로켓그로스 입고 해보신 분 계신가요",
    "상세페이지 바꾸고 전환율이 좀 올랐어요",
    "다들 부가세 신고 준비하고 계시죠?",
    "오늘 주문이 몰려서 포장만 하다 하루가 갔네요",
    "반품 들어온 거 검수하다가 멘탈 나갔습니다",
    "네이버 쇼핑 검색 순위가 갑자기 밀리신 분 있나요",
    "키워드 광고 클릭당 단가가 너무 올랐어요",
    "사입 삼촌 수수료 요즘 얼마 정도 하나요?",
    "춘절 전에 발주 넣어야 하는데 벌써 걱정이네요",
    "배대지 어디 쓰세요? 요즘 통관이 느린 것 같아요",
    "세금계산서 발행을 깜빡해서 식겁했습니다",
    "신상 촬영 끝! 보정만 남았어요",
    "리뷰 이벤트 하니까 확실히 후기가 늘긴 하네요",
    "CS 전화가 하루에 서른 통은 오는 것 같아요",
    "택배비 또 오른다는데 사실인가요",
    "어제 라이브 방송 보러 와주신 분들 감사합니다",
    "프리랜서 3년 차인데 종소세가 제일 무섭네요",
    "클라이언트가 수정 요청을 열 번째 보내는 중입니다 ㅋㅋ",
    "계약서 없이 작업 시작하면 안 되는 이유를 오늘 또 배웠습니다",
    "포트폴리오 사이트 새로 만들었는데 피드백 주실 분 계실까요",
    "잔금 입금이 한 달째 안 들어오네요",
    "작업 단가를 올리고 싶은데 타이밍을 모르겠어요",
    "다들 작업용 모니터 뭐 쓰세요?",
    "오늘 미팅 세 건 뛰고 왔더니 녹초입니다",
    "피그마 업데이트되고 나서 좀 버벅이지 않나요",
    "인스타 릴스 조회수가 갑자기 터졌어요",
    "블로그 저품질 걸린 것 같은데 복구 방법 아시는 분",
    "메타 광고 계정이 또 비활성화됐어요 하...",
    "ROAS 300 넘기기가 이렇게 힘든 일이었나요",
    "이번 주 뉴스레터 오픈율이 괜찮게 나왔네요",
    "GA4 세팅은 아직도 헷갈립니다",
    "카카오 채널 친구 수 늘리는 팁 있을까요",
    "소상공인 정책자금 신청하신 분 계세요?",
    "사업자 카드는 어디 것이 혜택이 좋나요",
    "간이과세에서 일반과세로 넘어가면 뭐가 달라지나요",
    "직원 한 명 뽑았는데 4대 보험 처리가 복잡하네요",
    "가게 앞 공사 때문에 오늘은 손님이 없어요",
    "배민 리뷰 답글 다는 것도 일이네요",
    "원두 가격이 또 올랐습니다 사장님들",
    "점심 장사 끝! 이제 좀 쉬어요",
    "비 오는 날은 배달 주문만 들어오네요",
    "알바 구하기가 하늘의 별 따기입니다",
    "임대료 재계약 시즌이라 머리가 아파요",
    "신메뉴 반응이 생각보다 좋아요",
    "네이버 플레이스 사진 바꿨더니 예약이 늘었어요",
    "오늘도 다들 수고 많으셨습니다",
    "좋은 아침입니다! 오늘도 대박 나세요",
    "주말에도 출근하시는 분 손 🙋",
    "다들 퇴근은 하셨나요...",
    "커피 수혈하고 다시 달립니다",
    "월요일이라 그런지 문의가 많네요",
    "연말이라 그런지 물량이 장난 아니에요",
    "재고 실사하다가 하루가 다 갔어요",
    "바코드 프린터 잘 아시는 분 계신가요",
    "송장 출력 프로그램 뭐 쓰세요?",
    "엑셀 주문서 정리를 자동화하니까 신세계네요",
    "ChatGPT로 상품명 뽑아보신 분 계세요?",
    "썸네일 A/B 테스트 해보니까 차이가 꽤 나네요",
    "쿠팡 광고 입찰가는 어느 정도로 넣으세요?",
    "아이템위너를 뺏겨서 매출이 뚝 떨어졌어요",
    "해외 배송 문의가 부쩍 늘었어요",
    "환율 때문에 마진이 다 녹네요",
    "KC 인증 받는 데 얼마나 걸리셨어요?",
    "상표 등록은 꼭 미리 해두세요 여러분",
    "지재권 신고가 들어와서 상품 내렸습니다 ㅠ",
    "오픈마켓 수수료 정리된 표 있으신 분?",
    "정산이 늦어져서 자금이 빠듯하네요",
    "포장 박스 사이즈를 줄였더니 택배비가 꽤 절약돼요",
    "뽁뽁이 대신 종이 완충재 써보신 분 계세요?",
    "명절 전 마지막 출고일 공지 올리셨나요",
    "신규 고객보다 재구매 고객이 훨씬 소중하네요",
    "단골 손님이 지인을 데려오셨어요 뿌듯",
    "악성 리뷰 하나에 하루 종일 기분이 안 좋네요",
    "오늘 처음으로 일 매출 100 찍었습니다!",
    "축하드려요!! 저도 얼른 따라가겠습니다",
    "와 대단하세요 비결 좀 풀어주세요",
    "저도 같은 문제 겪었는데 고객센터에 문의하니까 풀렸어요",
    "그건 판매자센터 공지사항에 올라와 있어요",
    "링크 공유 감사합니다 잘 볼게요",
    "정보 감사합니다 큰 도움 됐어요",
    "혹시 오프라인 모임은 언제 하나요?",
    "이번 주 스터디 주제가 뭐였죠?",
    "다음 달 박람회 가시는 분 계세요?",
    "동대문 야간 시장 요즘 분위기 어떤가요",
    "샘플 받아봤는데 퀄리티가 사진이랑 다르네요",
    "MOQ 맞추기가 부담스러워요",
    "공장 납기가 일주일 밀렸습니다...",
    "원단 가격 협상 팁 있을까요",
    "신상 반응 보고 리오더 넣으려고요",
    "시즌 오프 세일은 언제부터 하세요?",
    "모델 섭외 비용이 생각보다 세네요",
    "제품 영상은 직접 찍으시나요?",
    "숏폼 하나 만드는 데 반나절이 걸려요",
    "유튜브 구독자 천 명 달성했습니다 🎉",
    "편집 프로그램은 다빈치로 갈아탔어요",
    "워드프레스 플러그인이 충돌 나서 밤샜네요",
    "서버 이전하다가 메일이 다 날아갈 뻔했어요",
    "결제 모듈 심사가 생각보다 오래 걸리네요",
    "도메인 연장 깜빡하면 큰일 납니다 여러분",
    "노션으로 업무 정리하시는 분 템플릿 공유해요",
    "슬랙이랑 카톡 중에 뭐가 편하세요?",
    "재택 3년 차인데 허리가 남아나질 않네요",
    "공유오피스로 옮길까 고민 중입니다",
    "세무사님 바꾸고 나서 마음이 편해졌어요",
    "통장 쪼개기 하니까 자금 관리가 훨씬 쉬워요",
    "폐업 신고 절차 아시는 분 계실까요 ㅠ",
    "버티는 게 이기는 거라고 믿고 있습니다",
    "오늘이 지원사업 서류 마감이라 정신없네요",
    "사업계획서 쓰다가 현타 왔어요",
    "IR 자료 피드백 주실 분 계신가요",
    "첫 직원 채용 공고 올렸습니다 떨리네요",
    "거래처 미수금은 어떻게 받아내시나요",
    "단가 인상 공문 보내야 하는데 문구가 고민이에요",
    "택배 파업 소식 들으셨어요?",
    "물류센터 입고가 지연된다고 문자 왔네요",
    "여름 비수기는 어떻게 버티시나요",
    "다음 주에 신상 20개 올릴 예정입니다 화이팅",
    "ㅋㅋㅋㅋ 공감합니다",
    "넵 확인했습니다!",
    "저도 궁금했는데 감사합니다",
    "오 이거 꿀팁이네요",
    "혹시 자료 공유 가능하실까요?",
    "답변 감사해요 바로 적용해 볼게요",
    "저희도 지난달에 똑같은 일 있었어요",
    "아 그 이슈 어제 공지 떴더라고요",
)
"""살 뜻이 드러나지 않는 평소 대화. 키워드 규칙에 걸리는 말은 넣지 않는다."""

_LONG_QUOTE_LINE = (
    "안녕하세요, 여성의류 쇼핑몰을 3년째 운영하고 있습니다. 이번에 자사몰을 새로 만들면서 "
    "상세페이지 템플릿이랑 메인 배너까지 한 번에 맡기려고 하는데요, 상품 수는 120개 정도이고 "
    "촬영 원본은 저희가 드릴 수 있습니다. 다음 달 중순 오픈이 목표예요. 비슷한 작업을 해보신 "
    "디자이너분이나 팀이 계시면 포트폴리오와 함께 견적 부탁드립니다. 예산은 협의할 수 있고, "
    "오픈 뒤 월 단위 유지보수도 같이 이야기하고 싶어요."
)
_LONG_ADS_LINE = (
    "안녕하세요. 반려동물 간식 브랜드를 운영하고 있는데요, 그동안 광고를 직접 돌리다가 한계가 "
    "와서 광고 대행을 알아보고 있습니다. 월 광고비는 500만 원 안팎이고 메타랑 네이버 쇼핑 "
    "위주예요. 수수료 구조나 계약 기간, 리포트를 어떻게 받는지 같은 걸 먼저 겪어보신 분들 "
    "이야기를 듣고 싶습니다. 소규모 브랜드 경험이 많은 곳이면 더 좋겠어요. 편하게 답글 주세요!"
)


class IntentKind(StrEnum):
    """살 뜻이 보이는 글의 갈래."""

    QUOTE = "quote"  # 견적·외주 문의
    VENDOR = "vendor"  # 업체 추천·소개 부탁
    ADS = "ads"  # 광고·마케팅 대행 문의


_CREATIVE_WORKS: tuple[str, ...] = (
    "상세페이지 제작", "로고 디자인", "쇼핑몰 구축", "홈페이지 리뉴얼", "제품 사진 촬영",
    "패키지 디자인", "유튜브 영상 편집", "숏폼 영상 제작", "앱 개발", "스마트스토어 세팅",
    "블로그 운영", "인스타그램 계정 운영", "배너 디자인", "자사몰 개발", "모델 촬영",
    "브랜드 네이밍", "카탈로그 디자인", "CS 상담", "번역", "뉴스레터 제작", "챗봇 구축",
    "ERP 연동 개발", "제품 소개 영상 제작", "리플렛 디자인",
)  # fmt: skip
_VENDOR_WORKS: tuple[str, ...] = (
    *_CREATIVE_WORKS,
    "3PL 물류", "물류 대행", "풀필먼트", "세무 기장", "인쇄", "해외 배송 대행", "상표 출원",
    "통관 대행", "매장 인테리어", "간판 제작",
)  # fmt: skip
_AD_CHANNELS: tuple[str, ...] = (
    "네이버 검색", "메타", "인스타그램", "유튜브", "쿠팡", "카카오", "구글", "틱톡", "블로그",
    "당근", "네이버 쇼핑", "스마트스토어",
)  # fmt: skip


@dataclass(frozen=True)
class _IntentBook:
    lines: tuple[str, ...]
    """그대로 쓰는 글."""
    templates: tuple[str, ...]
    """{} 자리에 fillers 가운데 하나를 넣어 쓰는 글."""
    fillers: tuple[str, ...]


_INTENT_BOOKS: dict[IntentKind, _IntentBook] = {
    IntentKind.QUOTE: _IntentBook(
        lines=(
            "상세페이지 제작 견적 받아보고 싶은데 어디에 문의하면 될까요?",
            "로고 디자인 외주 맡겨보신 분 계세요? 비용이 궁금합니다",
            "쇼핑몰 리뉴얼 견적 좀 받아보려고 하는데요",
            "제품 촬영 외주 주려는데 단가가 어느 정도인가요",
            "앱 개발 외주 견적 받아보신 분 후기 좀 들려주세요",
            "영상 편집 외주 구합니다. 주 2편 정도예요",
            "패키지 박스 제작 견적 문의드립니다. 수량은 1,000개예요",
            "홈페이지 제작 견적이 곳마다 너무 달라서 고민이에요",
            "3PL 견적 비교해 보신 분 계신가요?",
            "CS 외주로 돌리시는 분들 만족하시나요",
            "매장 인테리어 견적 받았는데 평당 얼마가 적당한 건가요",
            "번역 외주 급하게 구해요. 영문 상세페이지 20장입니다",
            _LONG_QUOTE_LINE,
        ),
        templates=(
            "{} 견적 받아보고 싶은데 잘하는 곳 있을까요?",
            "{} 외주 맡기려고 하는데 보통 얼마 정도 하나요?",
            "혹시 {} 견적 내주실 수 있는 분 계신가요?",
            "{} 외주 구합니다. 관심 있으신 분은 편하게 답글 주세요",
            "{} 견적 문의드려요. 일정이 급해서 빠르게 진행하고 싶습니다",
            "{} 쪽 외주 써보신 분들 만족도 어떠셨어요?",
            "{} 견적이 곳마다 너무 달라서요, 적정 가격이 얼마쯤인가요",
            "이번에 {} 외주로 돌리려고요. 경험 있으신 분 조언 부탁드려요",
            "{} 견적 비교해 보신 분 계시면 공유 부탁드립니다",
            "{} 외주 단가가 궁금합니다. 처음 맡겨봐서요",
        ),
        fillers=_CREATIVE_WORKS,
    ),
    IntentKind.VENDOR: _IntentBook(
        lines=(
            "택배 계약 업체 추천 좀 해주세요. 월 500건 정도 나가요",
            "세무 기장 업체추천 부탁드립니다",
            "믿을 만한 중국 구매대행 업체 소개 좀 부탁드려요",
            "상세페이지 잘하는 곳 추천 부탁드립니다",
            "스마트스토어 세팅해 주는 업체 추천받습니다",
            "물류 대행 업체소개 해주실 분 계실까요",
            "포장 부자재 싸게 파는 곳 추천부탁드려요",
            "촬영 스튜디오 추천 부탁드려요. 서울 쪽이면 좋겠어요",
            "인쇄 업체 추천해 주실 분~ 리플렛을 급하게 뽑아야 해요",
            "괜찮은 노무 업체 소개해 주실 수 있을까요?",
            "풀필먼트 업체  추천 좀요 (소량도 받아주는 곳으로요)",
        ),
        templates=(
            "{} 업체 추천 부탁드려요",
            "{} 잘하는 업체 추천 좀 해주세요",
            "{} 업체추천 받습니다. 소규모 물량도 괜찮은 곳이면 좋겠어요",
            "{} 쪽으로 괜찮은 곳 추천 부탁드립니다",
            "{} 업체 소개해 주실 분 계신가요?",
            "믿을 만한 {} 업체 소개 부탁드려요",
            "{} 괜찮은 곳 추천부탁드려요 ㅠㅠ",
            "{} 업체 추천해 주시면 커피 쏘겠습니다 ㅎㅎ",
            "혹시 {} 괜찮은 업체 소개받을 수 있을까요",
            "{} 업체  추천 좀요. 지금 쓰는 곳이 너무 느려서요",
        ),
        fillers=_VENDOR_WORKS,
    ),
    IntentKind.ADS: _IntentBook(
        lines=(
            "광고 대행 맡겨보신 분 계세요? 수수료가 궁금해요",
            "네이버 검색광고대행 써보신 분 후기 좀요",
            "인스타 마케팅 대행 알아보고 있는데 비용이 천차만별이네요",
            "광고대행사 바꾸려고 하는데 계약 기간이 걸리네요",
            "마케팅대행 맡기면 월 얼마 정도 드나요?",
            "메타 광고 대행 수수료 15%면 적당한 건가요",
            "블로그 마케팅 대행은 효과가 있긴 한가요?",
            "쿠팡 광고 대행 해주는 곳 찾고 있어요",
            _LONG_ADS_LINE,
        ),
        templates=(
            "{} 광고 대행 맡겨보신 분 계세요?",
            "{} 광고대행 수수료는 보통 몇 퍼센트인가요",
            "{} 마케팅 대행 알아보는 중인데 후기가 궁금해요",
            "{} 마케팅대행 써보니까 어떠셨어요?",
            "{} 광고 대행 해주실 분 찾습니다. 월 예산은 200~300 정도예요",
            "{} 쪽 광고 대행사 괜찮은 데 아시나요",
            "소규모 셀러인데 {} 마케팅 대행 맡길 만할까요?",
            "{} 광고 대행 계약할 때 꼭 확인해야 할 게 있을까요",
        ),
        fillers=_AD_CHANNELS,
    ),
}
_INTENT_WEIGHTS: dict[IntentKind, int] = {
    IntentKind.QUOTE: 50,
    IntentKind.VENDOR: 32,
    IntentKind.ADS: 18,
}
_MIXED_INTENT_LINES: tuple[str, ...] = (
    "광고 대행 업체 추천 부탁드려요. 월 예산은 300 정도입니다",
    "유튜브 채널 운영 외주 맡길 만한 업체 소개 부탁드립니다",
    "마케팅 대행 견적 받아봤는데 이 정도면 괜찮은 건지 봐주실 수 있나요",
    "상세페이지 외주 업체 추천 좀 해주세요",
)
"""두 갈래에 함께 걸리는 글."""

_NOTICES: tuple[str, ...] = (
    "📌 홍보 글은 운영진 확인을 받은 뒤에만 올릴 수 있어요",
    "이번 주 정기 모임은 목요일 저녁 8시입니다",
    "새로 들어오신 분들은 공지를 먼저 읽어 주세요",
    "질문은 검색을 먼저 해보고 올려 주시면 감사하겠습니다",
)
_BOT_LINES: tuple[str, ...] = (
    "새로 오신 분 환영합니다! 공지를 먼저 확인해 주세요.",
    "[자동 알림] 업체 추천 글은 금요일 홍보 스레드에만 올려 주세요.",
    "[자동 알림] 외주 구인 글에는 예산과 일정을 꼭 적어 주세요.",
    "도배 방지를 위해 같은 글은 10분 뒤에 다시 올릴 수 있어요.",
    "오늘의 환율 알림: 원/달러 환율이 전일보다 조금 올랐어요.",
)


def intent_message(rng: random.Random, kind: IntentKind | None = None) -> str:
    """살 뜻이 보이는 글 하나. kind 를 주면 그 갈래의 글만 고른다."""
    if kind is None:
        if rng.random() < _MIXED_INTENT_SHARE:
            return rng.choice(_MIXED_INTENT_LINES)
        kinds = tuple(_INTENT_WEIGHTS)
        kind = rng.choices(kinds, weights=[_INTENT_WEIGHTS[k] for k in kinds])[0]
    book = _INTENT_BOOKS[kind]
    if rng.random() < _FIXED_INTENT_SHARE:
        return rng.choice(book.lines)
    return rng.choice(book.templates).format(rng.choice(book.fillers))


def random_message(rng: random.Random) -> str:
    """그룹에 올라올 법한 글 하나. INTENT_RATIO 만큼은 살 뜻이 보이는 글이다."""
    if rng.random() < INTENT_RATIO:
        return intent_message(rng)
    return rng.choice(CHATTER)


# ---------------------------------------------------------------------------
# 사람들
# ---------------------------------------------------------------------------

# (성, 로마자, 흔한 정도)
_SURNAMES: tuple[tuple[str, str, int], ...] = (
    ("김", "kim", 21), ("이", "lee", 15), ("박", "park", 9), ("최", "choi", 5), ("정", "jung", 5),
    ("강", "kang", 3), ("조", "cho", 3), ("윤", "yoon", 3), ("장", "jang", 2), ("임", "lim", 2),
    ("한", "han", 2), ("오", "oh", 2), ("서", "seo", 2), ("신", "shin", 2), ("권", "kwon", 2),
    ("황", "hwang", 2), ("안", "ahn", 2), ("송", "song", 2), ("전", "jeon", 1), ("홍", "hong", 1),
    ("유", "yoo", 1), ("고", "ko", 1), ("문", "moon", 1), ("양", "yang", 1), ("손", "son", 1),
    ("배", "bae", 1), ("백", "baek", 1), ("허", "heo", 1), ("남", "nam", 1), ("심", "shim", 1),
)  # fmt: skip
_SURNAME_WEIGHTS = [weight for _, _, weight in _SURNAMES]
_GIVEN_NAMES: tuple[tuple[str, str], ...] = (
    ("지우", "jiwoo"), ("민준", "minjun"), ("서연", "seoyeon"), ("도윤", "doyun"),
    ("하은", "haeun"), ("예준", "yejun"), ("서윤", "seoyun"), ("시우", "siwoo"),
    ("지호", "jiho"), ("지민", "jimin"), ("수아", "sua"), ("주원", "juwon"),
    ("하준", "hajun"), ("지유", "jiyu"), ("건우", "gunwoo"), ("서현", "seohyun"),
    ("유진", "yujin"), ("현우", "hyunwoo"), ("민서", "minseo"), ("은지", "eunji"),
    ("태현", "taehyun"), ("수빈", "subin"), ("예은", "yeeun"), ("승현", "seunghyun"),
    ("지훈", "jihoon"), ("동현", "donghyun"), ("채원", "chaewon"), ("다은", "daeun"),
    ("성민", "sungmin"), ("재현", "jaehyun"), ("민지", "minji"), ("준호", "junho"),
    ("소연", "soyeon"), ("영호", "youngho"), ("미경", "mikyung"), ("상훈", "sanghoon"),
    ("혜진", "hyejin"), ("정우", "jungwoo"), ("은영", "eunyoung"), ("태윤", "taeyun"),
    ("가은", "gaeun"), ("민재", "minjae"), ("유나", "yuna"), ("진우", "jinwoo"),
    ("세영", "seyoung"), ("현정", "hyunjung"), ("재석", "jaeseok"), ("보람", "boram"),
    ("경민", "kyungmin"), ("나연", "nayeon"), ("우진", "woojin"), ("소희", "sohee"),
    ("준영", "junyoung"), ("아름", "areum"), ("동욱", "dongwook"), ("지현", "jihyun"),
    ("선우", "sunwoo"), ("예린", "yerin"), ("민호", "minho"), ("하늘", "haneul"),
    ("태양", "taeyang"), ("준서", "junseo"), ("서준", "seojun"), ("연우", "yeonwoo"),
    ("다인", "dain"), ("시윤", "siyun"), ("은우", "eunwoo"), ("채은", "chaeeun"),
    ("윤서", "yunseo"), ("지안", "jian"), ("하린", "harin"), ("도현", "dohyun"),
    ("수현", "soohyun"), ("미나", "mina"), ("정민", "jungmin"), ("해진", "haejin"),
    ("기현", "kihyun"), ("주희", "juhee"), ("성호", "sungho"), ("은서", "eunseo"),
)  # fmt: skip
_BIRTH_YEARS = tuple(f"{year % 100:02d}" for year in range(1975, 2004))
_HANDLE_WORDS: tuple[str, ...] = (
    "seller", "store", "shop", "biz", "mkt", "design", "dev", "works", "studio", "kr",
    "official", "trade", "market", "lab",
)  # fmt: skip
_BRAND_STEMS: tuple[tuple[str, str], ...] = (
    ("모모", "momo"), ("하루", "haru"), ("달빛", "dalbit"), ("소소", "soso"), ("도담", "dodam"),
    ("라온", "raon"), ("누리", "nuri"), ("바른", "bareun"), ("미소", "miso"), ("단비", "danbi"),
    ("온기", "ongi"), ("새벽", "saebyeok"), ("포근", "pogeun"), ("담다", "damda"),
    ("오늘", "oneul"), ("그린", "green"), ("블루", "blue"), ("메이", "may"), ("루나", "luna"),
    ("코코", "coco"), ("베리", "berry"), ("올리", "olly"), ("써니", "sunny"), ("마루", "maru"),
    ("나무", "namu"), ("별하", "byeolha"), ("가온", "gaon"), ("다온", "daon"), ("이음", "ieum"),
    ("모아", "moa"), ("리브", "live"), ("스토어랩", "storelab"),
)  # fmt: skip
_BRAND_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("상회", "sanghoe"), ("스토어", "store"), ("마켓", "market"), ("스튜디오", "studio"),
    ("컴퍼니", "company"), ("디자인", "design"), ("랩", "lab"), ("공방", "gongbang"),
    ("상점", "shop"), ("샵", "shop"), ("몰", "mall"), ("팩토리", "factory"),
    ("커머스", "commerce"), ("트레이딩", "trading"), ("웍스", "works"), ("기획", "plan"),
)  # fmt: skip
# (호칭, 로마자, 이름 뒤에 붙는지)
_ROLES: tuple[tuple[str, str, bool], ...] = (
    ("마케터", "mkt", False), ("셀러", "seller", False), ("디자이너", "design", False),
    ("개발자", "dev", False), ("에디터", "editor", False), ("MD", "md", False),
    ("대표", "ceo", True), ("실장", "manager", True), ("작가", "writer", True),
    ("PD", "pd", True),
)  # fmt: skip
_NICKNAMES: tuple[str, ...] = (
    "Jay", "Mina", "Daniel", "Sunny", "Chloe", "Kevin", "Grace", "Ryan", "Stella", "Eric",
    "Hannah", "Leo", "Julie", "Sean", "Amy", "Brian", "Sophie", "Ian", "Bella", "Tony",
)  # fmt: skip
_BOTS: tuple[tuple[str, str], ...] = (
    ("그룹 도우미", "group_helper"), ("공지 알리미", "notice_alert"),
    ("스팸 지킴이", "spam_guard"), ("환영 인사", "welcome_kr"), ("환율 알림", "fx_alert"),
    ("택배 조회", "parcel_track"),
)  # fmt: skip


@dataclass(frozen=True)
class _Persona:
    first_name: str
    last_name: str | None
    handles: tuple[str, ...]
    """이 사람이 쓸 법한 아이디들."""


def _korean_person(rng: random.Random) -> _Persona:
    family, family_en, _ = rng.choices(_SURNAMES, weights=_SURNAME_WEIGHTS)[0]
    given, given_en = rng.choice(_GIVEN_NAMES)
    year = rng.choice(_BIRTH_YEARS)
    style = rng.random()
    if style < 0.6:
        first_name, last_name = family + given, None
    elif style < 0.85:
        first_name, last_name = given, family
    else:
        first_name, last_name = given, None
    return _Persona(
        first_name,
        last_name,
        (
            f"{given_en}_{family_en}{year}",
            f"{family_en}{given_en}",
            f"{given_en}{family_en}",
            f"{given_en}{year}",
            f"{given_en}_{rng.choice(_HANDLE_WORDS)}",
            f"{family_en}_{given_en}",
            f"{given_en}_{family_en}",
            f"im{given_en}{year}",
            f"{given_en}{family_en}{year}",
        ),
    )


def _brand(rng: random.Random) -> _Persona:
    stem, stem_en = rng.choice(_BRAND_STEMS)
    suffix, suffix_en = rng.choice(_BRAND_SUFFIXES)
    return _Persona(
        stem + suffix,
        None,
        (
            f"{stem_en}{suffix_en}",
            f"{stem_en}_{suffix_en}",
            f"{stem_en}{suffix_en}_kr",
            f"{stem_en}_{suffix_en}_official",
            f"{stem_en}{suffix_en}{rng.randrange(1, 100):02d}",
            f"hello_{stem_en}{suffix_en}",
        ),
    )


def _role_person(rng: random.Random) -> _Persona:
    role, role_en, after_name = rng.choice(_ROLES)
    family, _, _ = rng.choices(_SURNAMES, weights=_SURNAME_WEIGHTS)[0]
    given, given_en = rng.choice(_GIVEN_NAMES)
    year = rng.choice(_BIRTH_YEARS)
    first_name = f"{family}{given} {role}" if after_name else f"{role} {given}"
    return _Persona(
        first_name,
        None,
        (
            f"{given_en}_{role_en}",
            f"{role_en}_{given_en}",
            f"{given_en}{role_en}{year}",
            f"{role_en}{given_en}",
        ),
    )


def _nickname_person(rng: random.Random) -> _Persona:
    nickname = rng.choice(_NICKNAMES)
    _, family_en, _ = rng.choices(_SURNAMES, weights=_SURNAME_WEIGHTS)[0]
    year = rng.choice(_BIRTH_YEARS)
    last_name = f"{family_en[0].upper()}." if rng.random() < 0.3 else None
    nick = nickname.lower()
    return _Persona(
        nickname,
        last_name,
        (
            f"{nick}_{family_en}",
            f"{nick}{family_en}{year}",
            f"{nick}_{rng.choice(_HANDLE_WORDS)}",
            f"the{nick}{year}",
            f"{nick}{year}{family_en}",
        ),
    )


def _bot(rng: random.Random) -> _Persona:
    name, stem = rng.choice(_BOTS)
    return _Persona(name, None, (f"{stem}_bot",))


def _claim_handle(rng: random.Random, base: str, taken: set[str], *, bot: bool) -> str:
    """다른 사람과 겹치지 않는 아이디를 하나 정한다(대소문자를 구분하지 않고 비교한다)."""
    stem = base.removesuffix("_bot") if bot else base
    tail = "_bot" if bot else ""
    handle = base if len(base) >= 5 else f"{stem}{rng.randrange(100, 1000)}{tail}"
    while handle.lower() in taken:
        handle = f"{stem}{rng.randrange(10, 1000)}{tail}"
    taken.add(handle.lower())
    if not bot and rng.random() < 0.06:
        handle = "_".join(part.capitalize() for part in handle.split("_"))
    return handle


def _next_person(rng: random.Random, taken_ids: set[int], taken_handles: set[str]) -> TgUser:
    roll = rng.random()
    is_bot = roll < _BOT_SHARE
    if is_bot:
        persona = _bot(rng)
    elif roll < 0.47:
        persona = _korean_person(rng)
    elif roll < 0.69:
        persona = _brand(rng)
    elif roll < 0.84:
        persona = _role_person(rng)
    else:
        persona = _nickname_person(rng)

    username: str | None = None
    if is_bot or rng.random() >= _NO_USERNAME_SHARE:
        username = _claim_handle(rng, rng.choice(persona.handles), taken_handles, bot=is_bot)
    user_id = rng.randrange(180_000_000, 7_600_000_000)
    while user_id in taken_ids:
        user_id = rng.randrange(180_000_000, 7_600_000_000)
    taken_ids.add(user_id)
    return TgUser(
        id=user_id,
        username=username,
        first_name=persona.first_name,
        last_name=persona.last_name,
        is_bot=is_bot,
    )


@lru_cache(maxsize=8)
def demo_population(count: int) -> tuple[TgUser, ...]:
    """데모 세계의 사람들을 앞에서부터 count 명. 같은 순번은 언제나 같은 사람이다.

    앞의 POOL_SIZE 명이 그룹에서 실제로 말하는 사람들이고, 그 뒤는 지난 기록에만 나온다.
    유저 id 와 아이디는 서로 겹치지 않는다.
    """
    rng = random.Random(f"{_WORLD_SEED}:people")
    taken_ids: set[int] = set()
    taken_handles: set[str] = set()
    return tuple(_next_person(rng, taken_ids, taken_handles) for _ in range(count))


def _stand_in(key: str, phone: str | None) -> TgUser:
    """등록되지 않은 세션·번호의 주인. 같은 key 는 언제나 같은 사람이다."""
    rng = random.Random(f"{_WORLD_SEED}:account:{key}")
    given, given_en = rng.choice(_GIVEN_NAMES)
    return TgUser(
        id=8_000_000_000 + rng.randrange(900_000_000),
        username=f"{given_en}_{rng.choice(_HANDLE_WORDS)}{rng.randrange(10, 100)}",
        first_name=given,
        phone=phone,
    )


@dataclass(frozen=True)
class ChatCast:
    """그룹 하나에서 말하는 사람들."""

    members: tuple[TgUser, ...]
    chatty: tuple[TgUser, ...]
    """유난히 말이 많은 사람들. 아이디가 있는 유저라서 활동량 규칙에 걸린다."""
    weights: tuple[float, ...]
    """members 와 같은 순서의, 말할 차례가 돌아오는 정도."""


@lru_cache(maxsize=4096)
def demo_chat_cast(chat_id: int) -> ChatCast:
    """그 그룹에서 말하는 사람들. 같은 그룹은 언제나 같은 구성이다."""
    rng = random.Random(f"{_WORLD_SEED}:cast:{chat_id}")
    members = tuple(rng.sample(demo_population(POOL_SIZE), rng.randint(16, 34)))
    chatty = tuple(user for user in members if user.username and not user.is_bot)[:_CHATTY_PER_CHAT]
    weights = tuple(
        _CHATTY_WEIGHT if user in chatty else _BOT_WEIGHT if user.is_bot else 1.0
        for user in members
    )
    return ChatCast(members, chatty, weights)


def _chat_weight(chat: TgChat) -> float:
    """사람이 많은 그룹일수록 글이 자주 올라온다."""
    return math.sqrt(chat.member_count or 300)


# ---------------------------------------------------------------------------
# 링크별 가입 결과
# ---------------------------------------------------------------------------

_NEW_GROUP_TITLES: tuple[str, ...] = (
    "온라인 셀러 야간 수다방", "초보 사장님 질문방", "브랜드 런칭 준비방",
    "소규모 쇼핑몰 운영자 모임", "디자인 의뢰 게시판", "마케팅 실무 Q&A",
    "셀러 물류 정보 나눔", "1인 기업 대표 모임", "스몰 브랜드 대표 네트워크",
    "이커머스 실무자 수다방", "판매자 세금 고민방", "신규 창업자 정보 나눔",
    "주말 장사 사장님방", "온라인 판매 입문반", "프리랜서 일감 나눔터",
    "개발·디자인 협업방", "촬영 스튜디오 정보 나눔", "수입 소싱 초보방",
    "로컬 브랜드 사장님 모임", "셀러 광고 효율 스터디", "쇼핑몰 운영 고민 상담소",
    "상품 기획 MD 수다방", "사업자 네트워킹 라운지", "커머스 트렌드 읽기 모임",
    "퇴사 후 창업 준비방", "투잡 셀러 저녁 모임", "오프라인 매장 운영 팁",
    "청년 창업가 소통방", "여성 대표 네트워크", "동네 상권 사장님 연합",
    "디지털 노마드 한국 모임", "굿즈 제작자 정보 나눔", "소자본 창업 아이템 공유",
    "해외 판매 도전기", "셀러 번개 정모방", "마켓 운영 자동화 연구회",
)  # fmt: skip
"""새로 가입하는 그룹에 붙는 이름."""


class JoinPlanKind(StrEnum):
    JOINED = "joined"  # 바로 가입된다
    REQUESTED = "requested"  # 입장 요청이 되고, 얼마 뒤 승인된다
    EXPIRED = "expired"  # 초대 링크가 만료됐다
    PRIVATE = "private"  # 비공개라 들어갈 수 없다
    FLOOD = "flood"  # 처음 한 번은 요청 제한에 걸리고, 그 뒤에 가입된다


# 0~99 의 눈금에서 이 값 미만이면 그 결과다(위에서부터 처음 맞는 것).
_PLAN_SHARES: tuple[tuple[int, JoinPlanKind], ...] = (
    (70, JoinPlanKind.JOINED),
    (84, JoinPlanKind.REQUESTED),
    (89, JoinPlanKind.EXPIRED),
    (93, JoinPlanKind.PRIVATE),
    (100, JoinPlanKind.FLOOD),
)


@dataclass(frozen=True)
class JoinPlan:
    """링크 하나에 가입을 시도하면 벌어질 일."""

    kind: JoinPlanKind
    chat: TgChat
    flood_seconds: int
    """FLOOD 일 때 텔레그램이 기다리라고 하는 시간(60~120초)."""
    approval_point: float
    """REQUESTED 일 때 승인까지 걸리는 시간이 설정한 범위의 어디쯤인지(0~1)."""


def demo_join_plan(target: LinkTarget) -> JoinPlan:
    """링크에 가입을 시도했을 때의 결과. 링크가 같으면 언제나 같다."""
    digest = hashlib.sha256(f"{_WORLD_SEED}:join:{target.dedupe_key}".encode()).digest()
    roll = int.from_bytes(digest[:2], "big") % 100
    kind = next(kind for limit, kind in _PLAN_SHARES if roll < limit)
    if kind == JoinPlanKind.EXPIRED and target.kind == LinkKind.PUBLIC:
        kind = JoinPlanKind.PRIVATE  # 공개 아이디에는 만료가 없다
    number = int.from_bytes(digest[2:8], "big")
    chat = TgChat(
        id=-(1_000_000_000_000 + 1_100_000_000 + number % 1_500_000_000),
        title=_NEW_GROUP_TITLES[digest[8] % len(_NEW_GROUP_TITLES)],
        username=target.value.lower() if target.kind == LinkKind.PUBLIC else None,
        kind=GroupKind.SUPERGROUP,
        member_count=round(140 * 160 ** (int.from_bytes(digest[9:11], "big") / 65_535)),
    )
    return JoinPlan(
        kind=kind,
        chat=chat,
        flood_seconds=60 + digest[11] % 61,
        approval_point=digest[12] / 255,
    )


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def _format_wait(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}초"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}분 {rest}초" if rest else f"{minutes}분"


def _flood_error(seconds: int) -> TelegramError:
    seconds = max(1, seconds)
    return TelegramError(
        TgErrorCode.FLOOD_WAIT,
        f"텔레그램이 요청을 잠시 제한했어요. {_format_wait(seconds)} 뒤에 다시 시도할 수 있어요.",
        retry_after=seconds,
    )


def _session_format_error() -> TelegramError:
    return TelegramError(TgErrorCode.SESSION_FORMAT, _MSG_SESSION_FORMAT, permanent=True)


def _normalize_phone(phone: str) -> str:
    """'+' 와 숫자만 남긴다. 010 으로 시작하는 국내 형식은 +82 로 바꿔 받는다."""
    digits = re.sub(r"[\s()+.\-]", "", phone)
    if not (digits.isascii() and digits.isdigit() and 7 <= len(digits) <= 15):
        raise TelegramError(
            TgErrorCode.PHONE_INVALID,
            "전화번호가 올바르지 않아요. 국가 번호부터 넣어 주세요(예: +821012345678).",
            permanent=True,
        )
    if digits.startswith("0"):
        digits = f"82{digits[1:]}"
    return f"+{digits}"


def _compact(code: str) -> str:
    """'12 345', '12-345' 처럼 끊어 적은 코드를 붙인다."""
    return re.sub(r"[\s\-]", "", code)


def _requested(target: LinkTarget, chat: TgChat) -> JoinResult:
    """입장 요청 결과. 초대 링크는 미리보기(제목·인원)만, 공개 그룹은 그룹 정보까지 알 수 있다."""
    if target.kind == LinkKind.PUBLIC:
        return JoinResult(JoinOutcome.REQUESTED, chat=chat)
    return JoinResult(JoinOutcome.REQUESTED, title=chat.title, member_count=chat.member_count)


def _log_chatter_end(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        logger.error(
            "데모 대화를 만들던 태스크 %s 이(가) 오류로 끝났어요", task.get_name(), exc_info=error
        )


@dataclass
class _Login:
    """진행 중인 로그인 절차 하나."""

    phone: str
    expires_at: datetime
    password_needed: bool = False


@dataclass(frozen=True)
class _JoinRequest:
    """승인을 기다리는 입장 요청."""

    chat: TgChat
    approve_at: datetime | None
    """이 시각이 지나면 승인된 것으로 친다. None 이면 계속 기다린다."""


# ---------------------------------------------------------------------------
# 계정 연결
# ---------------------------------------------------------------------------


class DemoClient(AccountClient):
    """계정 하나의 가짜 연결. 연결돼 있는 동안 자기가 들어가 있는 그룹의 대화를 흘려보낸다."""

    def __init__(self, gateway: DemoGateway, account_id: int, session: str) -> None:
        self.account_id = account_id
        self.session = session
        self._gateway = gateway
        self._connected = False
        self._handler: MessageHandler | None = None
        self._closed: asyncio.Future[None] | None = None
        self._close_error: TelegramError | None = None
        self._chatter: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> TgUser:
        user = self._gateway.admit(self.session)
        if not self._connected:
            self._connected = True
            self._close_error = None
            self._closed = asyncio.get_running_loop().create_future()
            self._chatter = asyncio.create_task(
                self._emit_messages(), name=f"demo-chatter-{self.account_id}"
            )
            self._chatter.add_done_callback(_log_chatter_end)
            self._gateway.attach(self)
        return user

    async def disconnect(self) -> None:
        chatter = self.drop()
        if chatter is not None and chatter is not asyncio.current_task():
            await asyncio.wait({chatter})

    def drop(self, error: TelegramError | None = None) -> asyncio.Task[None] | None:
        """연결을 닫는다. error 를 주면 wait_closed() 가 그 오류를 던진다.

        대화를 만들던 태스크를 취소하고 돌려준다(끝나기를 기다리지는 않는다).
        """
        if not self._connected:
            return None
        self._connected = False
        self._close_error = error
        self._gateway.detach(self)
        if self._closed is not None and not self._closed.done():
            self._closed.set_result(None)
        chatter, self._chatter = self._chatter, None
        if chatter is not None:
            chatter.cancel()
        return chatter

    async def wait_closed(self) -> None:
        closed = self._closed
        if closed is None:
            return
        # 기다리던 쪽이 취소돼도 연결 자체는 그대로 둔다.
        await asyncio.shield(closed)
        if self._close_error is not None:
            raise self._close_error

    def set_message_handler(self, handler: MessageHandler | None) -> None:
        self._handler = handler

    async def join(self, target: LinkTarget) -> JoinResult:
        self._ready()
        gateway = self._gateway
        settled = gateway.settled_join(self.account_id, target)
        if settled is not None:
            return settled
        await asyncio.sleep(gateway.join_pause())
        self._ready()  # 기다리는 사이 끊겼을 수 있다
        return gateway.carry_out_join(self.account_id, target)

    async def find_membership(
        self, target: LinkTarget | None, tg_chat_id: int | None
    ) -> TgChat | None:
        self._ready()
        return self._gateway.membership(self.account_id, target, tg_chat_id)

    async def list_groups(self) -> list[TgChat]:
        self._ready()
        return list(self._gateway.chats_of(self.account_id))

    async def leave(self, tg_chat_id: int) -> None:
        self._ready()
        self._gateway.forget_chat(self.account_id, tg_chat_id)

    async def log_out(self) -> None:
        self._ready()
        chatter = self.drop()
        self._gateway.revoke_session(self.session)
        if chatter is not None and chatter is not asyncio.current_task():
            await asyncio.wait({chatter})

    def export_session(self) -> str:
        return self.session

    def _ready(self) -> None:
        """요청을 받을 수 있는 상태인지 본다. 끊겼거나 요청 제한 중이면 실제처럼 거절한다."""
        if not self._connected:
            raise TelegramError(TgErrorCode.NETWORK, _MSG_NOT_CONNECTED)
        self._gateway.refuse_if_limited(self.account_id)

    async def _emit_messages(self) -> None:
        """연결돼 있는 동안, 사람이 말하는 속도로 그룹 메시지를 하나씩 핸들러에 넘긴다."""
        gateway = self._gateway
        while True:
            await asyncio.sleep(gateway.pause())
            handler = self._handler
            if handler is None:
                continue
            message = gateway.compose(self.account_id)
            if message is None:
                continue
            try:
                await handler(message)
            except Exception:
                logger.exception(
                    "데모 메시지를 넘기다 문제가 생겼어요 (account_id=%s, chat_id=%s)",
                    self.account_id,
                    message.chat_id,
                )


# ---------------------------------------------------------------------------
# 게이트웨이
# ---------------------------------------------------------------------------


def _check_range(name: str, value: tuple[float, float], *, minimum: float) -> tuple[float, float]:
    low, high = value
    if not minimum <= low <= high:
        raise ValueError(f"{name} 은(는) {minimum} 이상이고 (작은 값, 큰 값) 순서여야 해요.")
    return low, high


class DemoGateway(TelegramGateway):
    """가짜 텔레그램. 세계는 메모리에만 있고, 켤 때마다 demo_seed 가 DB 를 보고 다시 채운다."""

    def __init__(
        self,
        *,
        pace: tuple[float, float] = (1.5, 4.0),
        join_delay: tuple[float, float] = (0.6, 1.8),
        approval_delay: tuple[float, float] = (60.0, 120.0),
        seed: int | None = None,
        clock: Clock = utcnow,
    ) -> None:
        """pace: 연결 하나가 메시지 하나를 내보내는 간격(초)의 범위.
        join_delay: 가입 요청에 답하기까지 걸리는 시간의 범위.
        approval_delay: 입장 요청이 승인되기까지 걸리는 시간의 범위.
        seed: 주면 누가 언제 무슨 말을 하는지가 매번 같다.
        """
        self._pace = _check_range("pace", pace, minimum=0.001)
        self._join_delay = _check_range("join_delay", join_delay, minimum=0.0)
        self._approval_delay = _check_range("approval_delay", approval_delay, minimum=0.0)
        self._rng = random.Random(seed)
        self._clock = clock

        self._identities: dict[str, TgUser] = {}
        """세션 → 그 세션의 주인."""
        self._phones: dict[str, TgUser] = {}
        self._revoked: set[str] = set()
        self._session_numbers = itertools.count(1001)
        self._logins: dict[str, _Login] = {}

        self._chats: dict[int, dict[int, TgChat]] = {}
        """account_id → 그 계정이 들어가 있는 그룹(tg_chat_id → 그룹)."""
        self._links: dict[tuple[int, str], int] = {}
        """(account_id, 링크의 dedupe_key) → 그 링크로 들어간 그룹의 tg_chat_id."""
        self._requests: dict[tuple[int, str], _JoinRequest] = {}
        self._flood_until: dict[int, datetime] = {}
        self._flooded_once: set[tuple[int, str]] = set()
        """요청 제한을 이미 한 번 겪은 (계정, 링크). 다음 시도에는 가입된다."""
        self._message_ids: dict[int, int] = {}
        self._connected: set[DemoClient] = set()

    # --- 세계를 채우는 장치 (demo_seed 와 테스트가 부른다) --------------------

    def register_session(self, session: str, user: TgUser) -> None:
        """이 세션으로 접속하면 user 가 나오게 한다. 번호가 있으면 그 번호로 로그인해도 같다."""
        if not session.startswith(SESSION_PREFIX):
            raise ValueError(f"데모 세션은 {SESSION_PREFIX} 로 시작해야 해요.")
        self._identities[session] = user
        if user.phone:
            self._phones[user.phone] = user

    def revoke_session(self, session: str) -> None:
        """세션을 만료시킨다. 이 세션으로는 더 접속할 수 없고, 접속해 있던 연결은 끊긴다."""
        self._revoked.add(session)
        for client in list(self._connected):
            if client.session == session:
                client.drop(
                    TelegramError(TgErrorCode.SESSION_INVALID, _MSG_SESSION_CLOSED, permanent=True)
                )

    def start_flood_wait(self, account_id: int, until: datetime) -> None:
        """이 계정을 until 까지 요청 제한에 건다. 그때까지의 요청은 FLOOD_WAIT 로 거절한다.

        이미 더 늦게 풀리는 제한이 걸려 있으면 그대로 둔다.
        """
        current = self._flood_until.get(account_id)
        if current is None or current < until:
            self._flood_until[account_id] = until

    def register_chat(
        self, account_id: int, chat: TgChat, *, target: LinkTarget | None = None
    ) -> None:
        """계정이 이 그룹에 들어가 있게 한다. target 은 그 그룹에 들어갈 때 쓴 링크다."""
        self._chats.setdefault(account_id, {})[chat.id] = chat
        if target is not None:
            key = (account_id, target.dedupe_key)
            self._links[key] = chat.id
            self._requests.pop(key, None)

    def register_request(
        self, account_id: int, target: LinkTarget, chat: TgChat, *, approve: bool = True
    ) -> None:
        """계정이 이 링크로 입장 요청을 보내 둔 상태로 만든다.

        approve=True 면 approval_delay 안에 승인되고, False 면 계속 승인을 기다린다.
        """
        approve_at = self._approval_time(target) if approve else None
        self._requests[(account_id, target.dedupe_key)] = _JoinRequest(chat, approve_at)

    def chats_of(self, account_id: int) -> tuple[TgChat, ...]:
        """계정이 지금 들어가 있는 그룹들."""
        return tuple(self._chats.get(account_id, {}).values())

    # --- DemoClient 가 쓰는 것 ----------------------------------------------

    def admit(self, session: str) -> TgUser:
        """세션의 주인을 돌려준다. 쓸 수 없는 세션이면 TelegramError(SESSION_INVALID)."""
        if not session.startswith(SESSION_PREFIX):
            raise TelegramError(TgErrorCode.SESSION_INVALID, _MSG_REAL_SESSION, permanent=True)
        if session in self._revoked:
            raise TelegramError(TgErrorCode.SESSION_INVALID, _MSG_SESSION_EXPIRED, permanent=True)
        user = self._identities.get(session)
        if user is None:
            user = self._identities[session] = _stand_in(f"session:{session}", None)
        return user

    def attach(self, client: DemoClient) -> None:
        self._connected.add(client)

    def detach(self, client: DemoClient) -> None:
        self._connected.discard(client)

    def pause(self) -> float:
        return self._rng.uniform(*self._pace)

    def join_pause(self) -> float:
        return self._rng.uniform(*self._join_delay)

    def refuse_if_limited(self, account_id: int) -> None:
        """계정이 요청 제한 중이면 남은 시간을 담아 TelegramError(FLOOD_WAIT) 를 던진다."""
        until = self._flood_until.get(account_id)
        if until is None:
            return
        remaining = (until - self._clock()).total_seconds()
        if remaining <= 0:
            del self._flood_until[account_id]
            return
        raise _flood_error(math.ceil(remaining))

    def compose(self, account_id: int) -> IncomingMessage | None:
        """계정이 들어가 있는 그룹 가운데 한 곳에 올라온 새 글. 그룹이 없으면 None."""
        chats = [
            chat
            for chat in self._chats.get(account_id, {}).values()
            if chat.kind != GroupKind.CHANNEL
        ]
        if not chats:
            return None
        rng = self._rng
        chat = rng.choices(chats, weights=[_chat_weight(chat) for chat in chats])[0]
        sender: TgUser | None = None
        if rng.random() < _ANONYMOUS_SHARE:
            text = rng.choice(_NOTICES)
        else:
            cast = demo_chat_cast(chat.id)
            sender = rng.choices(cast.members, weights=cast.weights)[0]
            text = rng.choice(_BOT_LINES) if sender.is_bot else random_message(rng)
        message_id = self._message_ids.get(chat.id, 10_000 + abs(chat.id) % 90_000) + 1
        self._message_ids[chat.id] = message_id
        return IncomingMessage(
            account_id=account_id,
            chat_id=chat.id,
            message_id=message_id,
            sender=sender,
            text=text,
            date=self._clock(),
        )

    def settled_join(self, account_id: int, target: LinkTarget) -> JoinResult | None:
        """이미 들어가 있거나 입장 요청을 보내 둔 링크면 그 결과를, 처음 보는 링크면 None."""
        chat = self.membership(account_id, target, None)
        if chat is not None:
            return JoinResult(JoinOutcome.JOINED, chat=chat)
        request = self._requests.get((account_id, target.dedupe_key))
        return _requested(target, request.chat) if request is not None else None

    def carry_out_join(self, account_id: int, target: LinkTarget) -> JoinResult:
        """처음 보는 링크에 가입을 시도한 결과를 세계에 반영한다."""
        key = (account_id, target.dedupe_key)
        plan = demo_join_plan(target)
        kind = plan.kind
        if kind == JoinPlanKind.FLOOD:
            if key not in self._flooded_once:
                self._flooded_once.add(key)
                until = self._clock() + timedelta(seconds=plan.flood_seconds)
                self.start_flood_wait(account_id, until)
                raise _flood_error(plan.flood_seconds)
            kind = JoinPlanKind.JOINED
        if kind == JoinPlanKind.EXPIRED:
            raise TelegramError(
                TgErrorCode.INVITE_EXPIRED, "초대 링크가 만료됐어요.", permanent=True
            )
        if kind == JoinPlanKind.PRIVATE:
            raise TelegramError(
                TgErrorCode.PRIVATE,
                "비공개 그룹이거나 이 계정이 차단돼 있어서 들어갈 수 없어요.",
                permanent=True,
            )
        chat = self._as_known(plan.chat)
        if kind == JoinPlanKind.REQUESTED:
            self._requests[key] = _JoinRequest(chat, self._approval_time(target))
            return _requested(target, chat)
        self.register_chat(account_id, chat, target=target)
        return JoinResult(JoinOutcome.JOINED, chat=chat)

    def membership(
        self, account_id: int, target: LinkTarget | None, tg_chat_id: int | None
    ) -> TgChat | None:
        """계정이 그 그룹의 멤버면 그룹 정보를 돌려준다. 승인될 때가 된 입장 요청은 여기서 승인된다."""
        chats = self._chats.get(account_id, {})
        if tg_chat_id is not None and tg_chat_id in chats:
            return chats[tg_chat_id]
        if target is not None:
            linked = chats.get(self._links.get((account_id, target.dedupe_key), 0))
            if linked is not None:
                return linked
            if target.kind == LinkKind.PUBLIC:
                name = target.value.lower()
                for chat in chats.values():
                    if chat.username and chat.username.lower() == name:
                        return chat
        return self._approve_if_due(account_id, target, tg_chat_id)

    def forget_chat(self, account_id: int, tg_chat_id: int) -> None:
        """계정이 그룹에서 나간다. 멤버가 아니었으면 아무 일도 없다."""
        self._chats.get(account_id, {}).pop(tg_chat_id, None)
        for key in [key for key, chat_id in self._links.items() if chat_id == tg_chat_id]:
            if key[0] == account_id:
                del self._links[key]

    def _as_known(self, chat: TgChat) -> TgChat:
        """세계에 새로 들어올 방을 다듬는다.

        다른 계정이 이미 아는 방이면 그 정보를 그대로 쓰고, 처음 보는 방인데 이름이 이미 있는
        방과 겹치면 아직 쓰지 않은 이름을 붙인다(이름을 다 썼으면 겹친 채로 둔다).
        """
        known = [room for rooms in self._chats.values() for room in rooms.values()]
        known += [request.chat for request in self._requests.values()]
        for room in known:
            if room.id == chat.id:
                return room
        taken = {room.title for room in known}
        if chat.title not in taken or chat.title not in _NEW_GROUP_TITLES:
            return chat
        start = _NEW_GROUP_TITLES.index(chat.title)
        for step in range(1, len(_NEW_GROUP_TITLES)):
            title = _NEW_GROUP_TITLES[(start + step) % len(_NEW_GROUP_TITLES)]
            if title not in taken:
                return replace(chat, title=title)
        return chat

    def _approval_time(self, target: LinkTarget) -> datetime:
        low, high = self._approval_delay
        delay = low + (high - low) * demo_join_plan(target).approval_point
        return self._clock() + timedelta(seconds=delay)

    def _approve_if_due(
        self, account_id: int, target: LinkTarget | None, tg_chat_id: int | None
    ) -> TgChat | None:
        key: tuple[int, str] | None = None
        if target is not None and (account_id, target.dedupe_key) in self._requests:
            key = (account_id, target.dedupe_key)
        elif tg_chat_id is not None:
            key = next(
                (
                    candidate
                    for candidate, request in self._requests.items()
                    if candidate[0] == account_id and request.chat.id == tg_chat_id
                ),
                None,
            )
        if key is None:
            return None
        request = self._requests[key]
        if request.approve_at is None or self._clock() < request.approve_at:
            return None
        del self._requests[key]
        self._chats.setdefault(account_id, {})[request.chat.id] = request.chat
        self._links[key] = request.chat.id
        return request.chat

    # --- TelegramGateway ---------------------------------------------------

    def create_client(self, account_id: int, session: str) -> AccountClient:
        return DemoClient(self, account_id, session)

    async def start_login(self, phone: str) -> PendingLogin:
        number = _normalize_phone(phone)
        now = self._clock()
        # 만료된 절차와, 같은 번호로 먼저 시작한 절차는 버린다.
        self._logins = {
            login_id: login
            for login_id, login in self._logins.items()
            if login.expires_at > now and login.phone != number
        }
        login_id = secrets.token_urlsafe(18)
        expires_at = now + LOGIN_TTL
        self._logins[login_id] = _Login(number, expires_at)
        return PendingLogin(login_id=login_id, phone=number, code_via="app", expires_at=expires_at)

    async def submit_code(self, login_id: str, code: str) -> LoginResult:
        login = self._login(login_id)
        value = _compact(code)
        if not value:
            raise TelegramError(TgErrorCode.CODE_INVALID, "인증 코드를 넣어 주세요.")
        if value != DEMO_CODE:
            raise TelegramError(
                TgErrorCode.CODE_INVALID,
                f"인증 코드가 틀렸어요. 데모 모드의 코드는 {DEMO_CODE} 예요.",
            )
        if login.phone.endswith(TWO_FACTOR_PHONE_SUFFIX):
            login.password_needed = True
            return LoginResult(
                "password_required", password_hint=f"데모 비밀번호는 {DEMO_PASSWORD}"
            )
        return self._complete(login_id, login)

    async def submit_password(self, login_id: str, password: str) -> LoginResult:
        login = self._login(login_id)
        if not login.password_needed:
            raise TelegramError(TgErrorCode.CODE_INVALID, "인증 코드를 먼저 넣어 주세요.")
        if not password:
            raise TelegramError(TgErrorCode.PASSWORD_INVALID, "2단계 인증 비밀번호를 넣어 주세요.")
        if password != DEMO_PASSWORD:
            raise TelegramError(
                TgErrorCode.PASSWORD_INVALID,
                f"2단계 인증 비밀번호가 틀렸어요. 데모 모드의 비밀번호는 {DEMO_PASSWORD} 예요.",
            )
        return self._complete(login_id, login)

    async def cancel_login(self, login_id: str) -> None:
        self._logins.pop(login_id, None)

    async def import_session(self, data: str | bytes) -> LoginResult:
        if isinstance(data, bytes):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _session_format_error() from exc
        else:
            text = data
        session = text.strip()
        if not session.startswith(SESSION_PREFIX) or session == SESSION_PREFIX:
            raise _session_format_error()
        return LoginResult("done", session=session, user=self.admit(session))

    async def close(self) -> None:
        """로그인 절차를 모두 버리고, 열려 있는 연결을 닫아 대화를 멈춘다(세계는 그대로 둔다)."""
        self._logins.clear()
        for client in list(self._connected):
            await client.disconnect()

    def _login(self, login_id: str) -> _Login:
        login = self._logins.get(login_id)
        if login is None or login.expires_at <= self._clock():
            self._logins.pop(login_id, None)
            raise TelegramError(TgErrorCode.LOGIN_EXPIRED, _MSG_LOGIN_EXPIRED, permanent=True)
        return login

    def _complete(self, login_id: str, login: _Login) -> LoginResult:
        """로그인이 끝났다. 그 번호의 주인에게 새 세션을 내준다."""
        user = self._phones.get(login.phone) or _stand_in(f"phone:{login.phone}", login.phone)
        session = f"{SESSION_PREFIX}{next(self._session_numbers)}"
        while session in self._identities or session in self._revoked:
            session = f"{SESSION_PREFIX}{next(self._session_numbers)}"
        self.register_session(session, user)
        del self._logins[login_id]
        return LoginResult("done", session=session, user=user)
