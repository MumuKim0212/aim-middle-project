"""[역할] 금액 계산(상환액·총이자·DSR용 연간 상환액·스케줄·표기)을 Decimal로 정확하게 처리한다."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28
D = Decimal
REPAY = ("원리금균등분할", "만기일시상환", "원금균등분할")


def to_won(x: Decimal | float | int) -> int:
    """원 단위 반올림."""
    return int(D(str(x)).quantize(D("1"), rounding=ROUND_HALF_UP))


def _check(principal: int, rate: Decimal, n: int, method: str) -> None:
    if principal < 0 or n <= 0 or rate < 0 or method not in REPAY:
        raise ValueError("invalid repayment input")


def monthly_payment(principal: int, rate: Decimal, n: int, method: str) -> Decimal:
    """월 상환액(원금균등은 첫 달). rate는 연 %."""
    _check(principal, rate, n, method)
    p, r = D(principal), D(rate) / D(1200)
    if method == "만기일시상환":
        return p * r
    if method == "원금균등분할":
        return p / n + p * r
    if r == 0:
        return p / n
    return p * r / (1 - (1 + r) ** (-n))


def total_interest(principal: int, rate: Decimal, n: int, method: str) -> Decimal:
    _check(principal, rate, n, method)
    p, r = D(principal), D(rate) / D(1200)
    if method == "만기일시상환":
        return p * r * n
    if method == "원금균등분할":
        return p * r * (n + 1) / 2
    return monthly_payment(principal, rate, n, method) * n - p


def annual_for_dsr(principal: int, rate: Decimal, n: int, method: str, collateral: str) -> Decimal:
    """DSR용 연간 원리금: 전월세·예금담보는 이자만, 만기일시는 원금÷max(n/12,1)+이자."""
    p = D(principal)
    if collateral in ("JEONSE", "DEPOSIT"):
        return p * D(rate) / 100
    if method == "만기일시상환":
        return p / max(D(n) / 12, D(1)) + p * D(rate) / 100
    return monthly_payment(principal, rate, n, method) * 12


def add_months(d: date, months: int) -> date:
    """월 더하기(말일 보정)."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(a: date, b: date) -> int:
    """달력상 개월 차이(일자 무시)."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def schedule(balance: int, rate: Decimal, remain: int, method: str, start: date, paid: int = 0) -> list[dict]:
    """잔액이 0원이 될 때까지 남은 회차 전부. 마지막 회차는 잔액을 모두 원금으로 정리."""
    _check(balance, rate, max(remain, 1), method)
    r = D(rate) / D(1200)
    bal = int(balance)                        # 원 단위 정수로 잔액을 추적해 원금 합계가 정확히 대출금과 같게 한다
    pay = monthly_payment(balance, rate, remain, method) if method == "원리금균등분할" else D(0)
    even = to_won(D(balance) / remain) if method == "원금균등분할" else 0
    rows = []
    for k in range(1, remain + 1):
        if bal <= 0:
            break
        it = to_won(D(bal) * r)
        if method == "만기일시상환":
            pp = bal if k == remain else 0
        elif method == "원금균등분할":
            pp = even
        else:
            pp = max(to_won(pay) - it, 0)
        if k == remain or pp > bal:
            pp = bal
        bal -= pp
        rows.append({"seq": paid + k, "due_date": add_months(start, paid + k), "principal": pp,
                     "interest": it, "balance_after": bal})
    return rows


def kwon(n: int | Decimal) -> str:
    """화면용 금액 표기: 1만원 미만 원 단위, 그 이상 'N억 M,MMM만원'(만 단위 반올림)."""
    n = to_won(n)
    if n < 0:
        return "-" + kwon(-n)
    if n < 10_000:
        return f"{n:,}원"
    eok, rest = divmod(n, 100_000_000)
    man = to_won(D(rest) / D(10_000))
    if man == 10_000:
        eok, man = eok + 1, 0
    s = (f"{eok}억" if eok else "") + ((" " if eok else "") + f"{man:,}만" if man else "")
    return s + "원"


def won(n: int | Decimal) -> str:
    return f"{to_won(n):,}원"
