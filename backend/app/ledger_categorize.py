"""카드 거래 자동 분류.

카드 서비스가 쌓는 거래(card_transactions)에는 가계부 분류(ledger_tx_category)가 없다. 그대로 두면 전부 '기타'로
잡혀서 분류별 예산·추이가 의미가 없어진다. 분류가 없는 승인 거래를 사용처 이름으로 분류해서 source='auto' 로 저장한다.

  1. 규칙: 사용처 이름에 분류 말(치킨·스타벅스·택시·마트 …)이 들어 있으면 그 분류
  2. LLM : 규칙으로 못 정한 사용처만 Gemini 한 번에 묶어서 물어본다(키가 없거나 실패하면 '기타')
사용자가 직접 고친 분류(source='user')는 건드리지 않는다. 취소 거래는 원 승인 거래의 분류를 따른다.
"""
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .gemini import LlmUnavailable, generate_json
from .ledger_nlu import CATEGORIES, _CATEGORY_WORDS

log = logging.getLogger("ledger.categorize")

# 가맹점 이름에 자주 나오는 말(NLU 의 분류 말에 더해서 쓴다)
_MERCHANT_WORDS: dict[str, list[str]] = {
    "배달": ["배달", "배민", "요기요", "쿠팡이츠", "치킨", "피자", "족발", "야식", "맘스터치", "bhc", "bbq"],
    "외식": ["식당", "카페", "커피", "스타벅스", "투썸", "이디야", "맥도날드", "버거", "김밥", "국밥", "고기", "술집", "베이커리", "빵집", "분식"],
    "장보기": ["마트", "이마트", "홈플러스", "롯데마트", "gs25", "cu", "세븐일레븐", "편의점", "농협", "하나로", "식자재"],
    "쇼핑": ["쿠팡", "11번가", "지마켓", "옥션", "올리브영", "무신사", "다이소", "백화점", "아울렛", "온라인 쇼핑", "의류", "신발"],
    "교통": ["택시", "카카오t", "버스", "지하철", "코레일", "ktx", "srt", "주유", "gs칼텍스", "sk에너지", "주차", "하이패스", "티머니"],
    "생활": ["통신", "kt", "skt", "lg유플러스", "관리비", "전기", "가스", "수도", "보험", "병원", "약국", "의원", "학원", "교육", "헬스", "넷플릭스", "유튜브", "멜론", "구독", "생활비", "세탁", "미용"],
}

_last_run: dict[str, float] = {}
THROTTLE_SEC = 20  # 같은 회원은 이 시간 안에는 다시 훑지 않는다(화면이 자주 새로고침돼도 부담이 없게)

_SYSTEM = """카드 사용처 이름을 가계부 분류로 나눈다. 각 이름마다 다음 중 하나만 고른다: 배달, 외식, 장보기, 쇼핑, 교통, 생활, 기타.
(통신·구독·병원·교육·보험·공과금은 생활, 식당·카페는 외식, 마트·편의점은 장보기.) 모르면 기타. JSON 으로만 답한다."""
_SCHEMA = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"merchant": {"type": "STRING"}, "category": {"type": "STRING", "enum": CATEGORIES}},
        "required": ["merchant", "category"]}}},
    "required": ["items"],
}


def classify_by_rules(merchant: str) -> str | None:
    name = merchant.lower()
    for cat, words in _MERCHANT_WORDS.items():
        if any(w in name for w in words):
            return cat
    for cat in CATEGORIES:
        if cat in merchant:
            return cat
    for cat, words in _CATEGORY_WORDS.items():
        if any(w in merchant for w in words):
            return cat
    return None


def _classify_with_llm(merchants: list[str]) -> dict[str, str]:
    try:
        raw = generate_json(_SYSTEM, "\n".join(merchants[:30]), _SCHEMA, timeout_default=8.0)
    except LlmUnavailable:
        return {}
    out = {}
    for it in raw.get("items") or []:
        if it.get("merchant") in merchants and it.get("category") in CATEGORIES:
            out[it["merchant"]] = it["category"]
    return out


def ensure_categories(db: Session, user_id: int, force: bool = False) -> int:
    """분류가 없는 승인 거래에 자동 분류를 채운다. 새로 채운 건수를 돌려준다."""
    now = time.monotonic()
    if not force and now - _last_run.get(user_id, 0) < THROTTLE_SEC:
        return 0
    _last_run[user_id] = now
    rows = db.execute(
        select(m.CardTransaction.id, m.CardTransaction.merchant)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(m.LedgerTxCategory, m.LedgerTxCategory.card_transaction_id == m.CardTransaction.id)
        .where(m.Card.user_id == user_id, m.CardTransaction.kind == "approval",
               m.LedgerTxCategory.card_transaction_id.is_(None))
        .limit(200)
    ).all()
    if not rows:
        return 0
    decided = {mid: classify_by_rules(name) for mid, name in rows}
    unknown = sorted({name for mid, name in rows if decided[mid] is None})
    by_llm = _classify_with_llm(unknown) if unknown else {}
    for tx_id, name in rows:
        cat = decided[tx_id] or by_llm.get(name) or "기타"
        db.add(m.LedgerTxCategory(card_transaction_id=tx_id, user_id=user_id, category=cat, source="auto"))
    db.commit()
    log.info("카드 거래 %d건 자동 분류", len(rows))
    return len(rows)
