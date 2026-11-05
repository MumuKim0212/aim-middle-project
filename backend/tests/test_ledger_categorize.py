"""카드 거래 자동 분류(규칙) 점검. DB·LLM 없이 돈다.

실행: backend 폴더에서  python tests/test_ledger_categorize.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ledger_categorize import classify_by_rules  # noqa: E402

CASES = [
    ("스타벅스 강남점", "외식"), ("배달의민족", "배달"), ("BHC치킨 역삼점", "배달"), ("쿠팡이츠", "배달"),
    ("이마트 성수", "장보기"), ("GS25 편의점", "장보기"), ("쿠팡", "쇼핑"), ("올리브영", "쇼핑"),
    ("카카오T 택시", "교통"), ("지하철 티머니", "교통"), ("넷플릭스", "생활"), ("KT 통신요금", "생활"),
    ("OO내과의원", "생활"), ("온라인 쇼핑", "쇼핑"), ("생활비 결제", "생활"),
    ("모르는가게", None),
]


def test_rules():
    wrong = [f"{name}: 기대 {want} / 실제 {classify_by_rules(name)}" for name, want in CASES if classify_by_rules(name) != want]
    assert not wrong, "\n" + "\n".join(wrong)


if __name__ == "__main__":
    test_rules()
    print(f"ok ({len(CASES)} cases)")
