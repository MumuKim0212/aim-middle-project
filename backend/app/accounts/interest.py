"""이자 계산(계좌.md 6장). 세전·단리·일할, 원 단위 절사. API·자연어 도구·해지 처리가 모두 이 함수를 쓴다."""
import calendar
from datetime import date
from decimal import Decimal


def add_months(d: date, n: int) -> date:
    """n개월 뒤 같은 날(없으면 그 달의 말일)."""
    y, mo = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, mo + 1, min(d.day, calendar.monthrange(y, mo + 1)[1]))


def _bp(rate: Decimal | float | str) -> int:
    """연금리(%, 소수 둘째 자리)를 1/10000 단위 정수로: 2.90 → 290. 부동소수점 오차를 피한다."""
    return int(Decimal(str(rate)) * 100)


def deposit_interest(principal: int, rate, start: date, end: date) -> int:
    """정기예금: 원금 × 연금리 × 일수 / 365."""
    return principal * _bp(rate) * max((end - start).days, 0) // (365 * 10_000)


def savings_interest(payments: list[tuple[date, int]], rate, end: date) -> int:
    """정기적금: Σ 납입금 × 연금리 × (종료일 − 납입일) / 365. 늦게 낸 회차는 낸 날부터 붙는다."""
    total = sum(amount * max((end - paid).days, 0) for paid, amount in payments)
    return total * _bp(rate) // (365 * 10_000)
