"""가계부 질문 해석. 문장 하나에서 의도·금액·카테고리를 뽑는다.

이 모듈이 "자연어 라우터"의 자리다.
  - LEDGER_NLU=rules : 규칙 기반 해석만 쓴다(시안의 해석 규칙, 키 필요 없음).
  - LEDGER_NLU=llm   : Gemini 로 먼저 해석하고, 키가 없거나 실패·시간 초과·이상한 응답이면 규칙 해석으로 되돌린다.

원칙: LLM 은 "무엇을 묻는지"만 해석한다. 금액 계산과 가능/보류 판정, 답변 문장은 LLM 이 하지 않는다.
LLM 응답은 JSON 스키마로 받고, 값(의도·카테고리·금액)을 우리 쪽에서 다시 검증한 뒤에만 쓴다.
API 키는 환경변수(GEMINI_API_KEY)로만 받고 로그·응답에 남기지 않는다.
"""
import logging
import os
import re
from dataclasses import dataclass
from decimal import Decimal

from .gemini import LlmUnavailable, generate_json

log = logging.getLogger("ledger.nlu")

CATEGORIES = ["배달", "외식", "장보기", "쇼핑", "교통", "생활", "기타"]
INTENTS = ["purchase", "balance", "budget", "last", "prev2", "chat"]
MAX_AMOUNT = 100_000_000


@dataclass(frozen=True)
class Understanding:
    intent: str  # purchase | balance | budget | last | prev2 | chat(잡담·불명확)
    amount: int | None
    category: str | None  # 문장에 카테고리 말이 없으면 None (직전 질문의 것을 이어받는다)
    source: str = "rules"  # rules | llm


# ───────────── 규칙 기반 ─────────────


def parse_amount(text: str) -> int | None:
    """'2만 원' → 20000, '20,000원' → 20000. 금액이 없으면 None."""
    man = re.search(r"(\d+(?:\.\d+)?)\s*만\s*원?", text)
    if man:
        return int(Decimal(man.group(1)) * 10000 + Decimal("0.5"))  # half-up
    won = re.search(r"(\d[\d,]{3,})\s*원?", text)
    if won:
        digits = re.sub(r"\D", "", won.group(1))
        return int(digits) if digits else None
    return None


_PURCHASE_HINT = re.compile(r"돼|될까|되나|되냐|시켜|사도|살까|먹어|먹을|결제|써도|쓸까|질러|지를|괜찮|가능|해도|주문|구매|사줘")


def classify(text: str, amount: int | None) -> str:
    if re.search(r"지지난달", text):
        return "prev2"
    if re.search(r"지난달|저번달", text):
        return "last"
    if re.search(r"잔액|통장|계좌", text):
        return "balance"
    if re.search(r"예산|얼마 남", text) and amount is None:
        return "budget"
    if amount is not None or _PURCHASE_HINT.search(text):
        return "purchase"
    return "chat"  # 인사·잡담·무슨 말인지 모를 때는 억지로 가계부 질문으로 끼워 맞추지 않는다


def find_category(text: str) -> str | None:
    return next((c for c in CATEGORIES if c in text), None)


def understand_rules(text: str) -> Understanding:
    amount = parse_amount(text)
    return Understanding(classify(text, amount), amount, find_category(text), "rules")


# ───────────── Gemini ─────────────

_SYSTEM = """너는 은행 가계부 앱의 '질문 해석기'다. 사용자의 한국어 문장 하나를 읽고 JSON 으로만 답한다.
계산하거나 조언하지 말고, 무엇을 묻는지만 분류한다.

intent (하나만):
- purchase : 어떤 것을 사거나 결제해도 되는지 묻는다(금액이 없어도 purchase).
- chat     : 인사, 잡담, 욕, 시비, 의미 없는 글자, 가계부와 상관없는 말, 무슨 뜻인지 알 수 없는 말.
             잔액·예산·지출을 묻는 말이 분명하지 않으면 억지로 다른 의도로 고르지 말고 chat.
- balance  : 계좌 잔액, 통장에 얼마 있는지, 카드값 빼고 얼마 남는지를 묻는다.
- budget   : 이번 달 남은 예산을 묻는다(결제 금액 이야기가 없을 때).
- last     : 지난달(저번 달)에 얼마 썼는지 묻는다.
- prev2    : 지지난달(두 달 전)에 얼마 썼는지 묻는다.

amount: 문장에 적힌 결제 금액을 원 단위 정수로. '2만 원'=20000, '삼만원'=30000, '이만 오천 원'=25000, '3천 원'=3000.
문장에 금액이 없으면 null. 금액을 추측하거나 지어내지 않는다.

category: 문장에 다음 중 하나가 분명히 나올 때만 그 값, 아니면 null.
배달, 외식, 장보기, 쇼핑, 교통, 생활, 기타
(치킨·피자·야식 시켜 먹기는 배달, 식당 가기는 외식, 마트·장은 장보기, 택시·지하철·버스는 교통)"""

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING", "enum": INTENTS},
        "amount": {"type": "INTEGER", "nullable": True},
        "category": {"type": "STRING", "enum": CATEGORIES, "nullable": True},
    },
    "required": ["intent", "amount", "category"],
}

# 금액을 말하는 글자가 문장에 하나도 없는데 LLM 이 금액을 주면 지어낸 것으로 본다
_NUMBER_HINT = re.compile(r"[0-9일이삼사오육칠팔구십백천만억]")


def _validate(raw: dict, text: str) -> Understanding:
    intent, amount, category = raw.get("intent"), raw.get("amount"), raw.get("category")
    if intent not in INTENTS:
        raise LlmUnavailable("bad intent")
    if category is not None and category not in CATEGORIES:
        category = None
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, int) or not (1 <= amount <= MAX_AMOUNT):
            raise LlmUnavailable("bad amount")
        if not _NUMBER_HINT.search(text):
            raise LlmUnavailable("amount not in text")
    return Understanding(intent, amount, category, "llm")


def understand_llm(text: str) -> Understanding:
    return _validate(generate_json(_SYSTEM, text, _SCHEMA), text)


def understand(text: str) -> Understanding:
    """질문 해석의 진입점."""
    if (os.getenv("LEDGER_NLU") or "rules").strip().lower() == "llm":
        try:
            llm = understand_llm(text)
        except LlmUnavailable as e:
            log.warning("LLM 해석 실패, 규칙으로 대체: %s", e)
        else:
            # 규칙이 금액을 확실히 읽어냈으면 규칙 값을 쓴다(숫자는 코드가 더 정확하다)
            rule_amount = parse_amount(text)
            amount = rule_amount if rule_amount is not None else llm.amount
            if llm.intent != "purchase":
                amount = None  # 금액은 결제 가능 여부를 물을 때만 의미가 있다
            return Understanding(llm.intent, amount, llm.category, "llm")
    return understand_rules(text)
