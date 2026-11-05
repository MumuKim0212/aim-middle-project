"""[역할] 적합성 판정·예상 금리·심사 파이프라인(main 5.2·6.2): 결격→소득→신용→DSR→담보→한도→판정."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal as D

from . import config as K
from .calculators import annual_for_dsr, kwon, monthly_payment, to_won


@dataclass
class Applicant:
    """심사 입력(고객정보확인서 + 조회 결과). 시나리오나 화면 입력으로 채운다."""
    job: str
    tenure: int
    income: int
    debt_monthly: int
    delinq_1y: bool
    amount: int
    term: int
    repay: str
    score: int
    inquiries: int = 0
    multi_debt: int = 0
    delinq_current: bool = False
    biz_closed: bool = False
    deposit: int = 0
    value: int = 0
    senior: int = 0
    price: int = 0
    dep_balance: int = 50_000_000


@dataclass
class Review:
    result: str
    limit: int
    rate: D
    dsr: D
    hard: list = field(default_factory=list)
    cond: list = field(default_factory=list)
    docs: list = field(default_factory=list)
    stages: list = field(default_factory=list)


def est_rate(product, score: int, income: int) -> D:
    """예상 금리(구현명세 6.2): 정부·협약·일반 산식, 소수 둘째 자리."""
    lo, hi = D(str(product["rate_min"])), D(str(product["rate_max"]))
    if product["business_type"] == "POLICY":
        add = D("0.5") if income > 60_000_000 else D("0.25") if income > 40_000_000 else D("0")
        return (lo + add).quantize(D("0.01"))
    if product["business_type"] == "INST" and product["inst_kind"] == "B":
        return (lo + (D("0.4") if score < 800 else D("0"))).quantize(D("0.01"))
    r = lo + D(max(0, 920 - score)) / 100 * D("0.9")
    return min(hi, max(lo, r)).quantize(D("0.01"))


def suitability(product, a: Applicant, excluded_monthly: int = 0) -> tuple[str, D]:
    """적합성 1차 판정(SUIT-RULE): 상품 최고 금리로 계산한 상환 부담률 70% 기준."""
    if a.income <= 0 and product["collateral_type"] != "DEPOSIT":
        return "UNSUITABLE", D("9.99")
    new_m = monthly_payment(a.amount, D(str(product["rate_max"])), a.term, a.repay)
    burden = (D(max(0, a.debt_monthly - excluded_monthly)) + new_m) / max(D(a.income) / 12, D(1))
    if burden > K.SUIT_MAX_BURDEN:
        return "UNSUITABLE", burden
    return ("WARNING" if a.delinq_1y else "SUITABLE"), burden


def adjust_plan(product, a: Applicant, refi: bool, excluded_monthly: int = 0) -> dict:
    """조정 안내(main 5.2.1): 기간 유지 시 최대 금액, 금액 유지 시 최소 기간."""
    rate = D(str(product["rate_max"]))
    r = rate / 1200
    budget = K.SUIT_MAX_BURDEN * D(a.income) / 12 - D(max(0, a.debt_monthly - excluded_monthly))
    max_amt = min_term = exact = None
    if budget > 0 and not refi:
        n = a.term
        if a.repay == "만기일시상환":
            amt = budget / r
        elif a.repay == "원금균등분할":
            amt = budget / (D(1) / n + r)
        else:
            amt = budget * (1 - (1 + r) ** (-n)) / r
        amt = int(min(amt, D(product["max_amount"])) // 1_000_000 * 1_000_000)
        max_amt = amt if amt >= product["min_amount"] else None
    if budget > 0 and a.repay != "만기일시상환":
        for t in range(1, 601):
            if monthly_payment(a.amount, rate, t, a.repay) <= budget:
                exact = t
                break
        min_term = next((t for t in sorted(product["term_options"]) if monthly_payment(a.amount, rate, t, a.repay) <= budget), None)
    return {"budget": to_won(budget), "max_amount": max_amt, "min_term": min_term, "exact_term": exact}


def review(product, a: Applicant, doc_defects: list[str], excluded_monthly: int = 0, suit_override: bool = False) -> Review:
    """심사 1~7단계. 같은 입력이면 항상 같은 결과(재현 가능)."""
    cat = product["collateral_type"]
    rate = est_rate(product, a.score, a.income)
    stress = rate + K.STRESS_ADD
    st = []
    if suit_override:
        st.append(("적합성 확인", "wa", "적합성 부적합 상태 · 고객이 고지를 확인하고 심사 진행에 동의함 (suitability_override 기록)"))
    ko = [c for c, on in (("KO-DELINQ-CURRENT", a.delinq_current), ("KO-BIZ-CLOSED", a.biz_closed)) if on]
    st.append(("결격(KO) 확인", "ng" if ko else "ok", ", ".join(ko) or "현재 연체·회생·명의도용·폐업 없음"))
    inc = []
    if cat != "DEPOSIT" and a.income < K.MIN_INCOME:
        inc.append("INC-BELOW-MIN")
    if cat != "DEPOSIT" and a.job == "급여소득자" and a.tenure < K.MIN_TENURE_MONTHS:
        inc.append("INC-TENURE-SHORT")
    st.append(("소득 확정", "ng" if inc else "ok", f"확정 연 소득 {kwon(a.income)}" + (f" · {', '.join(inc)}" if inc else "")))
    crd = []
    if a.score < K.MIN_CREDIT_SCORE:
        crd.append("CRD-SCORE-LOW")
    if a.multi_debt >= K.MULTI_DEBT_LIMIT:
        crd.append("CRD-MULTI-DEBT")
    if a.inquiries >= K.INQUIRY_LIMIT:
        crd.append("CRD-INQUIRY-MANY")
    st.append(("신용평가", "ng" if crd else "ok", f"신용평점 {a.score}점 · 예상 금리 연 {rate}%" + (f" · {', '.join(crd)}" if crd else "")))

    exist_a = D(max(0, a.debt_monthly - excluded_monthly)) * 12

    def dsr_at(amt: int) -> D:
        return (exist_a + annual_for_dsr(amt, stress, a.term, a.repay, cat)) / max(D(a.income), D(1))

    dsr = dsr_at(a.amount)
    lo, hi = D(0), D(product["max_amount"])
    if dsr_at(product["max_amount"]) <= K.DSR_LIMIT:
        lo = hi
    else:
        for _ in range(40):
            mid = (lo + hi) / 2
            if dsr_at(int(mid)) <= K.DSR_LIMIT:
                lo = mid
            else:
                hi = mid
    room = int(lo // 1_000_000 * 1_000_000)
    st.append(("DSR 계산", "ok" if dsr <= K.DSR_LIMIT else ("wa" if room >= product["min_amount"] else "ng"),
               f"DSR {(dsr * 100).quantize(D('0.1'))}% (스트레스 {stress}%) · 여유 한도 {kwon(room)}"))

    col_hard, col_cond, coll = [], [], None
    if cat == "MORTGAGE":
        coll = D(a.value) * K.LTV_LIMIT - a.senior
        if a.amount > coll:
            col_cond.append("COL-LTV-OVER")
    elif cat == "JEONSE":
        if a.senior + a.deposit > D(a.value) * K.JEONSE_RATIO_LIMIT:
            if a.senior > 0:
                col_hard.append("COL-SENIOR-LIEN")
            col_hard.append("COL-DEPOSIT-OVER-VALUE")
        coll = D(a.deposit) * K.JEONSE_LOAN_RATIO
    elif cat == "AUTO":
        coll = D(a.price) * K.AUTO_LOAN_RATIO
    elif cat == "DEPOSIT":
        coll = D(a.dep_balance) * K.DEPOSIT_LOAN_RATIO
    st.append(("담보·보증 평가", "ng" if col_hard else "wa" if col_cond else "ok", ", ".join(col_hard + col_cond) or ("담보 없음 (신용)" if coll is None else f"담보 한도 {kwon(coll)}")))

    cap = min([D(product["max_amount"]), D(room)] + ([coll] if coll is not None else []))
    limit = max(0, int(cap // 1_000_000 * 1_000_000))
    st.append(("한도 산출", "ok", f"한도 {kwon(limit)}"))

    hard = ko + inc + crd + col_hard + (["DSR-OVER"] if room < product["min_amount"] else [])
    cond: list[str] = []
    if hard:
        res = "REJECTED"
    elif doc_defects:
        res = "DOCS_REQUIRED"
    elif limit < a.amount:
        res = "COND_APPROVED"
        cond = (["DSR-OVER"] if dsr > K.DSR_LIMIT else []) + col_cond
    else:
        res = "APPROVED"
    st.append(("판정", {"APPROVED": "ok", "REJECTED": "ng"}.get(res, "wa"), res))
    return Review(res, limit, rate, dsr, hard, cond, list(doc_defects), st)
