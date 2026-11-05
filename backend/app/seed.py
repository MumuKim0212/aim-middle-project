"""개발용 시드 데이터. 카드 기획서 기준 데이터(member_001, acc_001/002, card_001/002)를 따른다."""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m

DEMO_MEMBER_ID = "member_001"


def _schedule(contract_no: str, start: date, amount: int, months: int, rate: float):
    """원금균등 상환 스케줄 (데모용 단순 계산)."""
    rows, balance = [], amount
    principal = amount // months
    for seq in range(1, months + 1):
        y, mo = divmod(start.month - 1 + seq, 12)
        due = date(start.year + y, mo + 1, min(start.day, 28))
        interest = round(balance * rate / 12)
        pay = principal if seq < months else balance
        balance -= pay
        rows.append(m.RepaymentSchedule(
            contract_no=contract_no, seq=seq, due_date=due,
            principal=pay, interest=interest, balance=balance))
    return rows


def _month_ago(d: date, n: int) -> date:
    y, mo = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, mo + 1, 1)


def _ensure_planned_outflows(db: Session) -> None:
    """가계부 예정 출금 데모 데이터 (이미 시드된 DB 에도 한 번만 추가)."""
    if db.scalar(select(m.PlannedOutflow.id).limit(1)):
        return
    today = date.today()
    y, mo = divmod(today.month, 12)
    pay_day = min(25, 28)
    due = date(today.year, today.month, pay_day)
    if due < today:  # 이번 달 결제일이 지났으면 다음 달
        due = date(today.year + y, mo + 1, pay_day)
    db.add_all([
        # 시안: 25일 카드대금 반영 후 예상 95,000원 = 1,245,000 - 1,150,000
        m.PlannedOutflow(id="po_001", member_id=DEMO_MEMBER_ID, due_date=due, amount=1_150_000,
                         type="card_bill", ref_type="card", ref_id="card_002"),
    ])
    db.commit()


def seed(db: Session) -> None:
    if db.get(m.Member, DEMO_MEMBER_ID):
        _ensure_planned_outflows(db)
        return
    today = date.today()
    month = today.strftime("%Y-%m")

    db.add(m.Member(id=DEMO_MEMBER_ID, login_id="demo", password_hash="!demo-no-login",
                    name="김민수", birth_date=date(1990, 5, 15), phone="010-1234-5678"))
    db.flush()
    db.add_all([
        m.Account(id="acc_001", member_id=DEMO_MEMBER_ID, bank_name="AIM Bank",
                  account_no_enc="enc:110-123-454821", account_masked="****4821",
                  balance=1_245_000, purpose="general", is_primary=True),
        m.Account(id="acc_002", member_id=DEMO_MEMBER_ID, bank_name="AIM Bank",
                  account_no_enc="enc:110-123-455678", account_masked="****5678",
                  balance=50_000, purpose="card_payment"),
        m.AccountPinState(account_id="acc_001"),
        m.AccountPinState(account_id="acc_002"),
    ])

    # 카드
    db.add_all([
        m.CardProduct(id="prod_debit_01", type="debit", name="AIM 체크카드", description="생활 영역 캐시백 체크카드"),
        m.CardProduct(id="prod_credit_01", type="credit", name="AIM 신용카드", description="후불 결제 신용카드"),
    ])
    db.flush()
    db.add_all([
        m.Card(id="card_001", member_id=DEMO_MEMBER_ID, product_id="prod_debit_01", name="AIM 체크카드",
               type="debit", number_last4="1111", expiry="03/30", issued_at=date(2025, 3, 10),
               payment_account_id="acc_001", payment_bank_name="AIM Bank", payment_account_masked="****4821",
               debit_per_tx=1_000_000, debit_per_day=3_000_000),
        m.Card(id="card_002", member_id=DEMO_MEMBER_ID, product_id="prod_credit_01", name="AIM 신용카드",
               type="credit", number_last4="2222", expiry="06/30", issued_at=date(2025, 6, 1),
               payment_account_id="acc_002", payment_bank_name="AIM Bank", payment_account_masked="****5678",
               payment_day=25, credit_limit=3_000_000),
    ])
    db.flush()
    # 가계부 시안(가계부_4가지_모드_체험.html)의 예시 데이터와 같은 값.
    # 이번 달 612,000원 = 생활 331,000 + 쇼핑 200,000 + 배달 81,000
    prev, prev2 = _month_ago(today, 1), _month_ago(today, 2)
    txs = [
        ("ctx_001", date(today.year, today.month, 1), "생활비 결제", 331_000, "생활"),
        ("ctx_002", date(today.year, today.month, 2), "온라인 쇼핑", 200_000, "쇼핑"),
        ("ctx_003", date(today.year, today.month, 3), "배달 주문", 81_000, "배달"),
        ("ctx_004", date(prev.year, prev.month, 8), "지난달 생활비", 300_000, "생활"),
        ("ctx_005", date(prev.year, prev.month, 13), "지난달 장보기", 160_000, "장보기"),
        ("ctx_006", date(prev.year, prev.month, 20), "지난달 배달", 120_000, "배달"),
        ("ctx_007", date(prev2.year, prev2.month, 8), "지지난달 생활비", 330_000, "생활"),
        ("ctx_008", date(prev2.year, prev2.month, 17), "지지난달 장보기", 130_000, "장보기"),
        ("ctx_009", date(prev2.year, prev2.month, 22), "지지난달 배달", 80_000, "배달"),
    ]
    for id_, day, merchant, amount, cat in txs:
        db.add(m.CardTransaction(id=id_, card_id="card_002", kind="approval",
                                 occurred_at=datetime.combine(day, datetime.min.time()).replace(hour=12),
                                 merchant=merchant, amount=amount))
    db.flush()
    for id_, _, _, _, cat in txs:
        db.add(m.LedgerTxCategory(card_transaction_id=id_, member_id=DEMO_MEMBER_ID, category=cat))

    # 가계부 예산: 월 800,000 / 배달 90,000
    db.add(m.Budget(id="bud_001", member_id=DEMO_MEMBER_ID, month=month, total_amount=800_000,
                    emergency_floor=0))
    db.flush()
    db.add_all([
        m.CategoryBudget(budget_id="bud_001", category="배달", amount=90_000),
        m.LedgerSettings(member_id=DEMO_MEMBER_ID, mode="roast", roast_level=2),
    ])

    # 대출 상품 (화면 시안의 상품 목록)
    catalog = [
        ("loan_g_01", "general", "OO 직장인 신용대출", 100_000_000, "1년 ~ 5년", ["일반대출", "신용"], "card"),
        ("loan_g_02", "general", "OO 스마트 전세대출", 220_000_000, "2년", ["일반대출", "전세"], "home"),
        ("loan_p_01", "gov", "정책 전세자금 (버팀목형)", 120_000_000, "2년", ["정부대출", "전세"], "home"),
        ("loan_p_02", "gov", "정책 주택구입자금 (디딤돌형)", 250_000_000, "10년 ~ 30년", ["정부대출", "주택담보"], "key"),
        ("loan_o_01", "org", "OO 협약기관 임직원 우대대출", 150_000_000, "1년 ~ 5년", ["기관대출", "신용"], "card"),
        ("loan_o_02", "org", "OO 보증부 전세대출", 500_000_000, "2년", ["기관대출", "전세"], "shield"),
        ("loan_r_01", "refi", "OO 신용대출 갈아타기", 100_000_000, "최대 5년", ["대환", "신용"], "swap"),
        ("loan_r_02", "refi", "OO 주택담보대출 갈아타기", 1_000_000_000, "최대 30년", ["대환", "주택담보"], "home"),
    ]
    for pid, typ, name, mx, term, tags, icon in catalog:
        db.add(m.ProductCatalog(product_id=pid, type=typ, name=name, version=1,
                                rules={"max_amount": mx, "term": term, "tags": tags, "icon": icon}))
    db.flush()

    # 내 대출 2건 (신청 → 조건 → 금리 → 약정 → 스케줄)
    loans = [
        ("loanapp_001", "LA-2025-000123", "loan_g_01", 30_000_000, 36, 0.0510, date(2025, 3, 10)),
        ("loanapp_002", "LA-2026-000412", "loan_r_01", 8_000_000, 24, 0.0450, date(2026, 10, 30)),
    ]
    for app_id, no, pid, amount, months, rate, start in loans:
        db.add(m.LoanApplication(id=app_id, member_id=DEMO_MEMBER_ID, product_type="general", status="contracted"))
        db.flush()
        db.add_all([
            m.LoanTerms(application_id=app_id, product_id=pid, amount=amount, term_months=months,
                        repay_method="원금균등"),
            m.Pricing(application_id=app_id, base_rate=rate - 0.012, spread=0.012, preferential=0, final_rate=rate),
            m.Contract(contract_no=no, application_id=app_id, signed_at=datetime.combine(start, datetime.min.time())),
        ])
        db.flush()
        db.add_all(_schedule(no, start, amount, months, rate))
    db.commit()
    _ensure_planned_outflows(db)
