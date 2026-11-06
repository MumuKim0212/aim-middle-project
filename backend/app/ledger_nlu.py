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
INTENTS = ["purchase", "balance", "budget", "last", "prev2", "record", "income", "week", "category", "daily", "query", "chat"]
MAX_AMOUNT = 100_000_000


@dataclass(frozen=True)
class Understanding:
    # purchase | balance | budget | last | prev2 | record(쓴 돈 기록) | week(이번 주) | category(분류별 합계) | daily(오늘 쓸 수 있는 돈) | query(그 밖의 가계부 조회·집계) | chat(잡담·불명확)
    intent: str
    amount: int | None
    category: str | None  # 문장에 카테고리 말이 없으면 None (직전 질문의 것을 이어받는다)
    source: str = "rules"  # rules | llm
    days_ago: int = 0  # record 일 때 며칠 전에 쓴 돈인지(오늘 0, 어제 1)
    hint: str | None = None  # record 일 때 사용처로 쓸 말("교육비", "치킨" 등). 없으면 분류 이름


# ───────────── 규칙 기반 ─────────────


def parse_amount(text: str) -> int | None:
    """'2만 원' → 20000, '20,000원' → 20000. 금액이 없으면 None."""
    man = re.search(r"(\d+(?:\.\d+)?)\s*만\s*(?:(\d+)\s*천)?\s*원?", text)
    if man:
        extra = int(man.group(2)) * 1000 if man.group(2) else 0  # '1만 5천'
        return int(Decimal(man.group(1)) * 10000 + Decimal("0.5")) + extra  # half-up
    chun = re.search(r"(\d+)\s*천\s*원?", text)
    if chun:
        return int(chun.group(1)) * 1000
    won = re.search(r"(\d[\d,]{3,})\s*원?", text)
    if won:
        digits = re.sub(r"\D", "", won.group(1))
        return int(digits) if digits else None
    return None


_PURCHASE_HINT = re.compile(r"돼|될까|되나|되냐|시켜|사도|살까|먹어|먹을|결제|써도|쓸까|질러|지를|괜찮|가능|해도|주문|구매|사줘")


# "어제 치킨 2만원 썼어"처럼 이미 쓴 돈을 말하는 문장(과거형). 물어보는 말투(돼?·괜찮아?·?)가 섞이면 기록이 아니다.
_RECORD_HINT = re.compile(r"썼|샀|먹었|시켰|결제했|긁었|질렀|나갔|지출했|냈|등록|기록|추가|넣어|적어|입력")
# "등록했어?" 처럼 방금 기록한 게 반영됐는지 되묻는 말(금액 없이)
# "응 등록해" 처럼 방금 얘기한 금액을 기록해 달라는 명령(금액 없이)
_RECORD_COMMAND = re.compile(r"(등록|기록|추가|입력|저장)\s*(해|할게|하자|좀|부탁)|넣어|적어")
_RECORD_CONFIRM = re.compile(r"(등록|기록|저장|반영|입력)\s*(했|됐|된|해뒀|돼)")
_ASKING = re.compile(r"돼|될까|되나|되냐|괜찮|가능|\?|\？|얼마나|어때")
# 돈이 들어온 이야기(수입). 금액이 있고 물어보는 말투가 아니면 수입 기록이다.
_INCOME_WORDS = ["월급", "급여", "용돈", "보너스", "상여", "환급", "이자", "부수입", "수입", "입금", "알바비", "페이"]
_INCOME_HINT = re.compile(r"월급|급여|용돈|보너스|상여|환급|이자|부수입|수입|입금|알바비|들어왔|받았|벌었")
# 정해 둔 의도에 안 맞지만 가계부 숫자를 묻는 말("금요일에 제일 많이 썼어?", "작년보다 늘었어?") → 자유 조회
_QUERY_ASK = re.compile(r"얼마|몇|가장|제일|평균|합계|총|비교|순위|최대|최소|언제|어느|요일|많이|적게|늘었|줄었|보여|알려")
_QUERY_TOPIC = re.compile(r"썼|쓴|지출|소비|결제|사용|수입|예산|거래|배달|외식|장보|쇼핑|교통|생활|카드|목표|저축|월급|입금")
_DAILY_HINT = re.compile(r"(오늘|하루).*(쓸 수|써도 되는|얼마까지|얼마 쓸|얼마나 쓸)|쓸 수 있는\s*(돈|금액)")
_WEEK_HINT = re.compile(r"이번\s*주|주간|일주일")
_SUM_HINT = re.compile(r"얼마|썼|쓴|지출|합계|총")


def income_source(text: str) -> str:
    """수입 이름: '월급', '용돈' 처럼 문장에 나온 말, 없으면 '수입'."""
    return next((w for w in _INCOME_WORDS if w in text), "수입")


def is_record_command(text: str) -> bool:
    return bool(_RECORD_COMMAND.search(text)) and not _RECORD_CONFIRM.search(text)


def parse_days_ago(text: str) -> int:
    """'어제'=1, '그저께'=2, 'N일 전'=N, 그 밖에는 오늘(0)."""
    if re.search(r"그저께|엊그제|그제", text):
        return 2
    if "어제" in text:
        return 1
    ago = re.search(r"(\d{1,2})\s*일\s*전", text)
    return min(int(ago.group(1)), 31) if ago else 0


def classify(text: str, amount: int | None) -> str:
    if re.search(r"지지난달", text):
        return "prev2"
    if re.search(r"지난달|저번달", text):
        return "last"
    if re.search(r"잔액|통장|계좌", text):
        return "balance"
    if amount is None and _DAILY_HINT.search(text):
        return "daily"
    if re.search(r"예산|얼마 남", text) and amount is None:
        return "budget"
    if amount is not None and _INCOME_HINT.search(text) and not _ASKING.search(text):
        return "income"
    if amount is not None and _RECORD_HINT.search(text) and not _ASKING.search(text):
        return "record"
    if amount is None and _INCOME_HINT.search(text) and not _ASKING.search(text) and "얼마" not in text:
        return "income"  # "월급 들어왔어" — 금액을 되묻는다
    if amount is None and (_RECORD_CONFIRM.search(text) or _RECORD_COMMAND.search(text)):
        return "record"
    if amount is None and _WEEK_HINT.search(text) and not _PURCHASE_HINT.search(text):
        return "week"
    if amount is None and find_category(text) and _SUM_HINT.search(text) and not _PURCHASE_HINT.search(text):
        return "category"
    if amount is not None or _PURCHASE_HINT.search(text):
        return "purchase"
    if amount is None and _QUERY_ASK.search(text) and _QUERY_TOPIC.search(text):
        return "query"
    return "chat"  # 인사·잡담·무슨 말인지 모를 때는 억지로 가계부 질문으로 끼워 맞추지 않는다


# 분류 이름 말고 흔히 쓰는 말로도 분류를 찾는다("치킨 2만원" → 배달)
_CATEGORY_WORDS = {
    "배달": ["치킨", "피자", "야식", "족발", "떡볶이", "배민", "요기요"],
    "외식": ["식당", "점심", "저녁", "카페", "커피", "술집", "회식"],
    "장보기": ["마트", "장보", "편의점", "식재료"],
    "쇼핑": ["옷", "신발", "쿠팡", "올리브영"],
    "교통": ["택시", "버스", "지하철", "주유", "기름"],
    "생활": ["교육", "학원", "병원", "약국", "통신", "구독", "관리비", "월세", "공과금", "보험", "미용", "세탁"],
}


def find_category_hint(text: str) -> tuple[str | None, str | None]:
    """(분류, 사용처로 쓸 말). 분류 이름이 직접 나오면 사용처 말은 None, 흔한 말로 찾았으면 그 말."""
    named = next((c for c in CATEGORIES if c in text), None)
    if named:
        return named, None
    for c, words in _CATEGORY_WORDS.items():
        for w in words:
            if w in text:
                # "교육비" 처럼 뒤에 붙은 '비'까지 사용처로 쓴다
                end = text.index(w) + len(w)
                return c, text[text.index(w):end + 1] if text[end:end + 1] == "비" else w
    return None, None


def find_category(text: str) -> str | None:
    return find_category_hint(text)[0]


def understand_rules(text: str) -> Understanding:
    amount = parse_amount(text)
    intent = classify(text, amount)
    cat, hint = find_category_hint(text)
    if intent == "income":
        hint = income_source(text)
    return Understanding(intent, amount, cat, "rules", parse_days_ago(text) if intent in ("record", "income") else 0, hint)


# ───────────── Gemini ─────────────

_SYSTEM = """너는 은행 가계부 앱의 '질문 해석기'다. 사용자의 한국어 문장 하나를 읽고 JSON 으로만 답한다.
계산하거나 조언하지 말고, 무엇을 묻는지만 분류한다.

intent (하나만):
- purchase : 어떤 것을 사거나 결제해도 되는지 묻는다(금액이 없어도 purchase).
- chat     : 인사, 잡담, 욕, 시비, 의미 없는 글자, 가계부와 상관없는 말, 무슨 뜻인지 알 수 없는 말.
             잔액·예산·지출을 묻는 말이 분명하지 않으면 억지로 다른 의도로 고르지 말고 chat.
- balance  : 계좌 잔액, 통장에 얼마 있는지, 카드값 빼고 얼마 남는지를 묻는다.
- budget   : 이번 달 남은 예산을 묻는다(월 예산, 분류별 예산 모두. "배달 말고 다른 예산은?" 같은 말도. 결제 금액 이야기가 없을 때).
- last     : 지난달(저번 달)에 얼마 썼는지 묻는다.
- prev2    : 지지난달(두 달 전)에 얼마 썼는지 묻는다.
- income   : 돈이 들어왔다고 알려 준다("월급 300만원 들어왔어", "5만원 용돈 받았어", "5만원 수입으로 등록해"). 금액이 있어야 한다.
- record   : 이미 쓴 돈을 알려 준다("어제 치킨 2만원 썼어", "오늘 점심 8천원 결제했어"). 금액이 있어야 한다.
- week     : 이번 주에 얼마 썼는지 묻는다.
- daily    : 오늘(하루) 얼마까지 쓸 수 있는지 묻는다.
- query    : 가계부 지출·수입·예산을 조회하거나 집계하는 질문인데 위 어느 것에도 딱 맞지 않는다(요일별, 순위, 평균, 기간 비교 등).
- category : 이번 달에 특정 분류(배달·외식 등)에 얼마 썼는지 묻는다.

amount: 문장에 적힌 결제 금액을 원 단위 정수로. '2만 원'=20000, '삼만원'=30000, '이만 오천 원'=25000, '3천 원'=3000.
문장에 금액이 없으면 null. 금액을 추측하거나 지어내지 않는다.

daysAgo: record 일 때 며칠 전에 쓴 돈인지(오늘 0, 어제 1, 그저께 2). record 가 아니거나 말이 없으면 0.

category: 문장에 다음 중 하나가 분명히 나올 때만 그 값, 아니면 null.
배달, 외식, 장보기, 쇼핑, 교통, 생활, 기타
(치킨·피자·야식 시켜 먹기는 배달, 식당 가기는 외식, 마트·장은 장보기, 택시·지하철·버스는 교통)"""

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING", "enum": INTENTS},
        "amount": {"type": "INTEGER", "nullable": True},
        "category": {"type": "STRING", "enum": CATEGORIES, "nullable": True},
        "daysAgo": {"type": "INTEGER", "nullable": True},
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
    days = raw.get("daysAgo")
    days = days if isinstance(days, int) and not isinstance(days, bool) and 0 <= days <= 31 else 0
    return Understanding(intent, amount, category, "llm", days)


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
            # 과거형으로 쓴 돈을 말한 문장(기록)과 '이번 주'는 규칙이 더 확실하다. 값을 등록하는 일이라 LLM 추측에 맡기지 않는다.
            rule = understand_rules(text)
            if rule.intent in ("record", "income", "week"):
                return Understanding(rule.intent, rule.amount, rule.category, "rules", rule.days_ago, rule.hint)
            # LLM 이 문장만 보고 잡담이라 했어도 규칙이 분명한 질문(예산·잔액·지난달 등)으로 읽었으면 규칙을 따른다
            if llm.intent == "chat" and rule.intent not in ("chat", "purchase"):
                return Understanding(rule.intent, None, rule.category, "rules")
            # 규칙이 금액을 확실히 읽어냈으면 규칙 값을 쓴다(숫자는 코드가 더 정확하다)
            rule_amount = parse_amount(text)
            intent = llm.intent
            # "3만원..." 처럼 금액만 말한 후속 답은 문장만 보면 잡담 같지만, 금액을 읽었으니 결제 질문으로 본다
            # (카테고리는 직전 질문에서 이어받는다)
            if intent == "chat" and rule_amount is not None:
                intent = "purchase"
            if intent == "record":  # 규칙이 기록으로 보지 않았으면 LLM 혼자 기록으로 등록하지 않는다(결제 질문으로 처리)
                intent = "purchase"
            amount = rule_amount if rule_amount is not None else llm.amount
            if intent != "purchase":
                amount = None  # 금액은 결제 가능 여부를 물을 때만 의미가 있다
            return Understanding(intent, amount, llm.category or rule.category, "llm", 0, rule.hint)
    return understand_rules(text)
