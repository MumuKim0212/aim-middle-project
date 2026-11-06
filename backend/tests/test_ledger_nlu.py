"""가계부 질문 해석(규칙) 점검용 문장 모음.

실행: backend 폴더에서  python -m pytest tests  (pytest 가 없으면  python tests/test_ledger_nlu.py)
LLM 은 쓰지 않는다. 규칙 해석이 문장을 어떻게 읽는지만 확인한다.
새로 이상하게 읽힌 문장이 나오면 CASES 에 한 줄 추가해서 다시 틀리지 않게 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ledger_nlu import parse_amount, understand_rules  # noqa: E402

# (문장, 의도, 금액, 분류, 며칠 전)  — 분류·며칠 전은 None 이면 확인하지 않는다
CASES = [
    # 결제해도 되는지
    ("오늘 배달 94,000원 시켜도 돼?", "purchase", 94000, "배달", None),
    ("3만원 쓸까?", "purchase", 30000, None, None),
    ("3만원...", "purchase", 30000, None, None),
    ("190,000원 결제해도 돼?", "purchase", 190000, None, None),
    ("오늘 외식 15,000원 썼어 괜찮아?", "purchase", 15000, "외식", None),
    ("지금 배달 시켜먹어도 되냐", "purchase", None, "배달", None),
    # 쓴 돈 기록
    ("어제 치킨 2만원 썼어", "record", 20000, "배달", 1),
    ("오늘 점심 8천원 결제했어", "record", 8000, "외식", 0),
    ("그저께 쇼핑 5만원 샀어", "record", 50000, "쇼핑", 2),
    ("3일 전 장보기 4만원 썼어", "record", 40000, "장보기", 3),
    ("어제 택시 1만 5천원 썼어", "record", 15000, "교통", 1),
    ("교육비로 2만원 등록", "record", 20000, "생활", 0),
    ("학원비 15만원 기록해줘", "record", 150000, "생활", 0),
    ("등록했어?", "record", None, None, None),
    ("5만원 수입으로 등록해", "income", 50000, None, 0),
    ("어제 월급 300만원 들어왔어", "income", 3000000, None, 1),
    ("5만원 용돈 받았어", "income", 50000, None, 0),
    ("월급 들어왔어", "income", None, None, None),
    # 조회
    ("이번 주 얼마 썼어", "week", None, None, None),
    ("이번 달 외식 얼마 썼어", "category", None, "외식", None),
    ("지난달엔?", "last", None, None, None),
    ("지지난달 얼마 썼지", "prev2", None, None, None),
    ("잔액 얼마야", "balance", None, None, None),
    ("남은 예산 알려줘", "budget", None, None, None),
    ("배달 얼마 남았어", "budget", None, "배달", None),
    ("배달 예산 제외 다른거는?", "budget", None, "배달", None),
    # 잡담
    ("야", "chat", None, None, None),
    ("왜 욕하냐", "chat", None, None, None),
]


def test_cases():
    wrong = []
    for text, intent, amount, category, days in CASES:
        u = understand_rules(text)
        got = (u.intent, u.amount, u.category, u.days_ago)
        want = (intent, amount, category if category is not None else u.category, days if days is not None else u.days_ago)
        if got != want:
            wrong.append(f"{text!r}: 기대 {want} / 실제 {got}")
    assert not wrong, "\n" + "\n".join(wrong)


def test_amounts():
    assert parse_amount("8천원") == 8000
    assert parse_amount("1만 5천원") == 15000
    assert parse_amount("2만원") == 20000
    assert parse_amount("20,000원") == 20000
    assert parse_amount("금액 없음") is None


if __name__ == "__main__":
    test_cases()
    test_amounts()
    print(f"ok ({len(CASES)} cases)")
