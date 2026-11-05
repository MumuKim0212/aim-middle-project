"""청구 주기 계산 (docs/card/00-api-common.md 6절).

상세·한도·청구·해지 판정이 모두 이 함수들을 쓴다. 거래 객체는 속성
(id, kind, occurred_at, amount, installment_months, original_id)만 있으면 된다.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def kst_date(dt: datetime) -> date:
    return dt.astimezone(KST).date()


def date_of(y: int, m: int, d: int) -> date:
    """월이 12를 넘거나 0 이하여도 연도로 넘겨서 계산한다 (d 는 1~28)."""
    return date(y + (m - 1) // 12, (m - 1) % 12 + 1, d)


def add_months(s: date, n: int) -> date:
    """같은 일자로 n개월 이동. 그 일자가 없으면 그 달의 마지막 날."""
    first = date_of(s.year, s.month + n, 1)
    last = date_of(first.year, first.month + 1, 1) - timedelta(days=1)
    return first.replace(day=min(s.day, last.day))


def piece(amount: int, n: int, i: int) -> int:
    return amount // n if i < n else amount - (amount // n) * (n - 1)


@dataclass
class Line:
    cycle: date
    kind: str  # approval | cancel | installment
    tx: object
    amount: int
    installment: tuple[int, int] | None  # (회차, 총 개월)


def cycle_of(day: date, d: int) -> date:
    """거래 날짜가 속한 달의 다음 달 D일."""
    return date_of(day.year, day.month + 1, d)


def cycle_lines(txs: list, d: int) -> list[Line]:
    by_id = {t.id: t for t in txs}
    lines: list[Line] = []
    for t in txs:
        day = kst_date(t.occurred_at)
        if t.kind == "approval":
            n = t.installment_months
            if n == 0:
                lines.append(Line(cycle_of(day, d), "approval", t, t.amount, None))
            else:
                for i in range(1, n + 1):
                    lines.append(Line(date_of(day.year, day.month + i, d), "installment", t,
                                      piece(t.amount, n, i), (i, n)))
        else:
            original = by_id.get(t.original_id)
            original_cycle = cycle_of(kst_date(original.occurred_at) if original else day, d)
            # 결제일(당일 포함) 전 취소는 원 주기에서, 이후 취소는 취소가 속한 주기에서 차감
            lines.append(Line(original_cycle if day <= original_cycle else cycle_of(day, d),
                              "cancel", t, t.amount, None))
    return lines


def cycle_totals(lines: list[Line]) -> dict[date, int]:
    totals: dict[date, int] = {}
    for ln in lines:
        totals[ln.cycle] = totals.get(ln.cycle, 0) + (-ln.amount if ln.kind == "cancel" else ln.amount)
    return totals


def billed(totals: dict[date, int], cycle: date) -> int:
    """B(P): 음수는 0, 이월 없음."""
    return max(0, totals.get(cycle, 0))


def used_amount(totals: dict[date, int], today: date) -> int:
    """결제일 당일까지는 미결제로 본다 (P >= today)."""
    return sum(max(0, v) for c, v in totals.items() if c >= today)


def usage_rate(used: int, total: int) -> float:
    return min(1000, (used * 1000 + total // 2) // total) / 10


def next_payment_date(today: date, d: int) -> date:
    """오늘 이후(당일 포함) 가장 가까운 결제일."""
    return date(today.year, today.month, d) if d >= today.day else date_of(today.year, today.month + 1, d)


def first_due_date(totals: dict[date, int], today: date) -> date | None:
    due = [c for c, v in totals.items() if c >= today and v > 0]
    return min(due) if due else None


def is_simple_pin(pin: str) -> bool:
    """모두 같거나, 앞 자리보다 항상 +1 또는 -1 씩 변하면 단순한 비밀번호."""
    diffs = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    return diffs in ({0}, {1}, {-1})
