"""개발용 시드 데이터. 카드 기획서 기준 데이터(member_001~004, acc_001/002/401/900, card_001~005/900)를 따른다."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete
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


KST = timezone(timedelta(hours=9))


def _kst(y: int, mo: int, d: int, hh: int = 12, mm: int = 0) -> datetime:
    return datetime(y, mo, d, hh, mm, tzinfo=KST)


def _reset_cards(db: Session) -> None:
    """카드 기준 데이터를 다시 넣기 위해 카드·거래 관련 행을 지운다 (FK 순서)."""
    for model in (m.LedgerTxCategory, m.PaymentAttempt, m.CardTransaction, m.CardApplication,
                  m.CardStatusHistory, m.Card, m.CardIssueQuota, m.CardProduct):
        db.execute(delete(model))


def _seed_cards(db: Session) -> None:
    """카드 기획서 00-api-common.md 10절 기준 데이터 (오늘 = 2026-11-04 기준 값). 계좌 암호는 모두 1234."""
    for mid, login, name, birth in [("member_002", "demo2", "이영희", date(1985, 3, 2)),
                                    ("member_003", "demo3", "박철수", date(1990, 1, 1)),
                                    ("member_004", "demo4", "최민준", date(2008, 6, 1))]:
        db.add(m.Member(id=mid, login_id=login, password_hash="!demo-no-login", name=name, birth_date=birth))
    db.flush()
    for acc, owner, masked, balance in [("acc_401", "member_004", "****4010", 100_000),
                                        ("acc_900", "member_002", "****9000", 700_000)]:
        db.add_all([m.Account(id=acc, member_id=owner, bank_name="AIM Bank", account_no_enc=f"enc:{masked}",
                              account_masked=masked, balance=balance, purpose="card_payment", is_primary=True),
                    m.AccountPinState(account_id=acc)])
    db.add_all([
        m.CardProduct(id="prod_debit_01", type="debit", name="AIM 체크카드", description="생활 영역 캐시백 체크카드"),
        m.CardProduct(id="prod_credit_01", type="credit", name="AIM 신용카드", description="후불 결제 신용카드"),
    ])
    db.flush()

    def card(id_, owner, type_, last4, expiry, issued, acc, masked, **kw):
        product = "prod_credit_01" if type_ == "credit" else "prod_debit_01"
        if type_ == "debit":
            kw = {"debit_per_tx": 1_000_000, "debit_per_day": 3_000_000, **kw}
        return m.Card(id=id_, member_id=owner, product_id=product, name="AIM 신용카드" if type_ == "credit" else "AIM 체크카드",
                      type=type_, number_last4=last4, expiry=expiry, issued_at=issued, payment_account_id=acc,
                      payment_bank_name="AIM Bank", payment_account_masked=masked, **kw)

    db.add_all([
        card("card_001", DEMO_MEMBER_ID, "debit", "1111", "03/30", date(2025, 3, 10), "acc_001", "****1234"),
        card("card_002", DEMO_MEMBER_ID, "credit", "2222", "06/30", date(2025, 6, 1), "acc_002", "****5678",
             payment_day=25, credit_limit=3_000_000),
        card("card_003", DEMO_MEMBER_ID, "credit", "3333", "09/30", date(2025, 9, 20), "acc_001", "****1234",
             payment_day=10, credit_limit=1_000_000, status="suspended", suspended_at=_kst(2026, 10, 30, 14, 5)),
        card("card_004", DEMO_MEMBER_ID, "credit", "4444", "01/31", date(2026, 1, 5), "acc_001", "****1234",
             payment_day=25, credit_limit=500_000, status="lost", lost_at=_kst(2026, 10, 20, 11, 30),
             lost_reason="lost"),
        card("card_005", DEMO_MEMBER_ID, "debit", "5555", "08/29", date(2024, 8, 30), "acc_001", "****1234",
             status="terminated", terminated_at=_kst(2026, 8, 30, 10)),
        card("card_900", "member_002", "debit", "9000", "05/30", date(2025, 5, 1), "acc_900", "****9000"),
    ])
    db.flush()

    # (id, card, 일시, 가맹점, 금액, 할부, 가계부 분류)
    approvals = [
        ("tx_205", "card_002", _kst(2026, 8, 10, 15, 40), "삼성전자", 900_000, 3, "shopping"),
        ("tx_201", "card_002", _kst(2026, 9, 12, 13, 10), "이마트", 120_000, 0, "shopping"),
        ("tx_202", "card_002", _kst(2026, 10, 5, 12, 20), "쿠팡", 300_000, 0, "shopping"),
        ("tx_203", "card_002", _kst(2026, 10, 18, 9, 5), "스타벅스 강남점", 12_000, 0, "food"),
        ("tx_206", "card_002", _kst(2026, 10, 30, 19, 30), "현대백화점", 600_000, 2, "shopping"),
        ("tx_207", "card_002", _kst(2026, 11, 2, 8, 10), "GS25", 8_000, 0, "food"),
        ("tx_401", "card_004", _kst(2026, 10, 15, 20), "올리브영", 45_000, 0, "shopping"),
    ] + [(f"tx_1{n:02d}", "card_001", _kst(2026, 10, n), f"편의점 {n:02d}호점", n * 1_000, 0, "food")
         for n in range(1, 31)]
    for id_, card_id, when, merchant, amount, inst, _ in approvals:
        db.add(m.CardTransaction(id=id_, card_id=card_id, kind="approval", occurred_at=when, merchant=merchant,
                                 amount=amount, installment_months=inst))
    db.flush()
    db.add(m.CardTransaction(id="tx_204", card_id="card_002", kind="cancel", occurred_at=_kst(2026, 10, 22, 10, 15),
                             merchant="스타벅스 강남점", amount=12_000, original_id="tx_203"))
    for id_, *_rest, category in approvals:
        db.add(m.LedgerTxCategory(card_transaction_id=id_, member_id=DEMO_MEMBER_ID, category=category))
    db.flush()


def seed(db: Session) -> None:
    if db.get(m.Member, DEMO_MEMBER_ID):
        if not db.get(m.Card, "card_900"):  # 예전 시드(카드 2장)를 기획서 기준 데이터로 바꾼다
            _reset_cards(db)
            _seed_cards(db)
            db.commit()
        return
    today = date.today()
    month = today.strftime("%Y-%m")

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

    _seed_cards(db)

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
