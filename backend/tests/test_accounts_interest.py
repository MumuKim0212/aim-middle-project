"""이자 계산(계좌.md 6장) 점검. DB 없이 돈다.

실행: backend 폴더에서  python -m pytest tests  (pytest 가 없으면  python tests/test_accounts_interest.py)
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.accounts.interest import add_months, deposit_interest, savings_interest  # noqa: E402


def test_deposit_full_year():
    # 300만원 × 2.9% × 365/365 = 87,000원
    assert deposit_interest(3_000_000, "2.90", date(2026, 1, 1), date(2027, 1, 1)) == 87_000


def test_deposit_truncates_to_won():
    # 1만원 × 2.9% × 1/365 = 0.79원 → 0원 (원 단위 절사)
    assert deposit_interest(10_000, "2.90", date(2026, 1, 1), date(2026, 1, 2)) == 0
    assert deposit_interest(1_000_000, "2.90", date(2026, 1, 1), date(2026, 1, 11)) == 794


def test_early_close_uses_lower_rate():
    full = deposit_interest(3_000_000, "2.90", date(2026, 1, 1), date(2026, 7, 1))
    early = deposit_interest(3_000_000, "1.00", date(2026, 1, 1), date(2026, 7, 1))
    assert early == 3_000_000 * 100 * 181 // (365 * 10_000) and early < full


def test_savings_sums_each_payment_from_its_own_date():
    # 20만원을 1월 1일에, 20만원을 2월 1일에 냈고 연 3.0% 로 3월 1일까지: (59일 + 28일) × 20만원 × 3% / 365
    pays = [(date(2026, 1, 1), 200_000), (date(2026, 2, 1), 200_000)]
    assert savings_interest(pays, "3.00", date(2026, 3, 1)) == 200_000 * (59 + 28) * 300 // (365 * 10_000)


def test_savings_late_payment_earns_from_paid_day():
    on_time = savings_interest([(date(2026, 2, 1), 100_000)], "3.00", date(2026, 3, 1))
    late = savings_interest([(date(2026, 2, 20), 100_000)], "3.00", date(2026, 3, 1))
    assert late < on_time


def test_no_negative_days():
    assert deposit_interest(1_000_000, "2.90", date(2026, 5, 1), date(2026, 4, 1)) == 0
    assert savings_interest([(date(2026, 5, 1), 100_000)], "3.00", date(2026, 4, 1)) == 0


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 5), 12) == date(2027, 11, 5)
    assert add_months(date(2026, 3, 15), -4) == date(2025, 11, 15)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
