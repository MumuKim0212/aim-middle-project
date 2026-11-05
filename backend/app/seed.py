"""개발용 시드 데이터. 카드 기획서 기준 데이터(member_001, acc_001/002, card_001/002)를 따른다."""
from datetime import date, datetime, timedelta

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


def seed(db: Session) -> None:
    if db.get(m.Member, DEMO_MEMBER_ID):
        return
    today = date.today()
    month = today.strftime("%Y-%m")

    def at(days_ago: int) -> datetime:
        d = max(1, today.day - days_ago)
        return datetime(today.year, today.month, d, 12, 0)

    db.add(m.Member(id=DEMO_MEMBER_ID, login_id="demo", password_hash="!demo-no-login",
                    name="김민수", birth_date=date(1990, 5, 15), phone="010-1234-5678"))
    db.flush()
    db.add_all([
        m.Account(id="acc_001", member_id=DEMO_MEMBER_ID, bank_name="AIM Bank",
                  account_no_enc="enc:110-123-451234", account_masked="****1234",
                  balance=2_000_000, purpose="general", is_primary=True),
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
               payment_account_id="acc_001", payment_bank_name="AIM Bank", payment_account_masked="****1234",
               debit_per_tx=1_000_000, debit_per_day=3_000_000),
        m.Card(id="card_002", member_id=DEMO_MEMBER_ID, product_id="prod_credit_01", name="AIM 신용카드",
               type="credit", number_last4="2222", expiry="06/30", issued_at=date(2025, 6, 1),
               payment_account_id="acc_002", payment_bank_name="AIM Bank", payment_account_masked="****5678",
               payment_day=25, credit_limit=3_000_000),
    ])
    db.flush()
    txs = [
        ("ctx_001", "card_002", at(1), "배달의민족", 21_000, "delivery"),
        ("ctx_002", "card_002", at(3), "스타벅스", 9_500, "food"),
        ("ctx_003", "card_001", at(4), "지하철", 1_450, "transport"),
        ("ctx_004", "card_002", at(6), "쿠팡", 89_000, "shopping"),
        ("ctx_005", "card_002", at(8), "GS25", 6_300, "food"),
    ]
    for id_, card, when, merchant, amount, cat in txs:
        db.add(m.CardTransaction(id=id_, card_id=card, kind="approval", occurred_at=when,
                                 merchant=merchant, amount=amount))
    db.flush()
    db.add(m.CardTransaction(id="ctx_006", card_id="card_002", kind="cancel", occurred_at=at(5),
                             merchant="쿠팡", amount=89_000, original_id="ctx_004"))
    for id_, _, _, _, _, cat in txs:
        db.add(m.LedgerTxCategory(card_transaction_id=id_, member_id=DEMO_MEMBER_ID, category=cat))

    # 가계부
    budget = m.Budget(id="bud_001", member_id=DEMO_MEMBER_ID, month=month, total_amount=800_000,
                      emergency_floor=100_000)
    db.add(budget)
    db.flush()
    db.add_all([
        m.CategoryBudget(budget_id="bud_001", category="delivery", amount=100_000),
        m.CategoryBudget(budget_id="bud_001", category="food", amount=200_000),
        m.LedgerSettings(member_id=DEMO_MEMBER_ID, mode="basic"),
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
