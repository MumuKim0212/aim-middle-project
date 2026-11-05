"""기획서 00-api-common.md 10.5절 기준값 검증. 실행: cd backend && python -m tests.test_card_cycles"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as Tx

from app.card_cycles import (
    add_months, billed, cycle_lines, cycle_totals, first_due_date, is_simple_pin, piece,
    usage_rate, used_amount,
)

KST = timezone(timedelta(hours=9))


def tx(id_, y, mo, d, hh, merchant, amount, kind="approval", inst=0, original=None):
    return Tx(id=id_, kind=kind, occurred_at=datetime(y, mo, d, hh, tzinfo=KST), merchant=merchant,
              amount=amount, installment_months=inst, original_id=original)


CARD_002 = [
    tx("tx_205", 2026, 8, 10, 15, "삼성전자", 900_000, inst=3),
    tx("tx_201", 2026, 9, 12, 13, "이마트", 120_000),
    tx("tx_202", 2026, 10, 5, 12, "쿠팡", 300_000),
    tx("tx_203", 2026, 10, 18, 9, "스타벅스 강남점", 12_000),
    tx("tx_204", 2026, 10, 22, 10, "스타벅스 강남점", 12_000, kind="cancel", original="tx_203"),
    tx("tx_206", 2026, 10, 30, 19, "현대백화점", 600_000, inst=2),
    tx("tx_207", 2026, 11, 2, 8, "GS25", 8_000),
]


def test_card_002_reference_values():
    totals = cycle_totals(cycle_lines(CARD_002, 25))
    assert billed(totals, date(2026, 10, 25)) == 420_000
    assert billed(totals, date(2026, 11, 25)) == 900_000
    assert billed(totals, date(2026, 12, 25)) == 308_000
    today = date(2026, 11, 4)
    assert used_amount(totals, today) == 1_208_000
    assert first_due_date(totals, today) == date(2026, 11, 25)
    assert usage_rate(1_208_000, 3_000_000) == 40.3


def test_late_cancel_goes_to_next_cycle():
    # 9/12 승인 -> 결제일 10/25, 11/2 취소 -> 12/25 청구에서 차감
    txs = [tx("a", 2026, 9, 12, 12, "x", 100_000), tx("b", 2026, 11, 2, 12, "x", 100_000, kind="cancel", original="a")]
    totals = cycle_totals(cycle_lines(txs, 25))
    assert totals[date(2026, 10, 25)] == 100_000 and totals[date(2026, 12, 25)] == -100_000
    assert billed(totals, date(2026, 12, 25)) == 0


def test_misc():
    assert [piece(1_000_000, 3, i) for i in (1, 2, 3)] == [333_333, 333_333, 333_334]
    assert usage_rate(45_000, 500_000) == 9.0 and usage_rate(999, 100) == 100.0
    assert add_months(date(2028, 2, 29), -12) == date(2027, 2, 28)
    assert [is_simple_pin(p) for p in ("1111", "1234", "3210", "7890", "1357")] == [True, True, True, False, False]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
