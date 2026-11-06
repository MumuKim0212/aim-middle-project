"""개발용 시드 데이터. 공통.md 7장(사용자 1~4, 계좌 1~6)과 카드 기획서 기준 데이터(card_001~005, 900)를 따른다."""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .accounts.interest import add_months
from .accounts.service import round_due
from .auth.security import hash_secret
from .loan.seed import setup as loan_setup

DEMO_USER_ID = 1  # user1 (김하나)
# 가계부 데모 거래는 카드 시드(card/00-api-common.md 10절)의 숫자를 흔들지 않도록 해지된 카드에 붙인다. 가계부는 카드 상태와 상관없이 사용자의 모든 카드 거래를 읽는다.
LEDGER_DEMO_CARD = "card_005"


KST = timezone(timedelta(hours=9))


def _kst(y: int, mo: int, d: int, hh: int = 12, mm: int = 0) -> datetime:
    return datetime(y, mo, d, hh, mm, tzinfo=KST)


def _ensure_cards(db: Session) -> None:
    """카드 기획서 00-api-common.md 10절의 나머지 카드·거래(카드 3~5, user2의 카드 900, 거래). 이미 있으면 건너뛴다.

    카드 1·2와 계좌는 seed() 가 만든다. 거래에는 가계부 분류를 넣지 않는다(가계부가 사용처 이름으로 자동 분류한다).
    """
    if db.get(m.Card, "card_900"):
        return

    def card(id_, user_id, type_, last4, expiry, issued, acc, masked, **kw):
        product = "prod_credit_01" if type_ == "credit" else "prod_debit_01"
        return m.Card(id=id_, user_id=user_id, product_id=product, name="AIM 신용카드" if type_ == "credit" else "AIM 체크카드",
                      type=type_, number_last4=last4, expiry=expiry, issued_at=issued, payment_account_id=acc,
                      payment_bank_name="AIM Bank", payment_account_masked=masked, **kw)

    db.add_all([
        card("card_003", DEMO_USER_ID, "credit", "3333", "09/30", date(2025, 9, 20), 1, "****1234",
             payment_day=10, credit_limit=1_000_000, status="suspended", suspended_at=_kst(2026, 10, 30, 14, 5)),
        card("card_004", DEMO_USER_ID, "credit", "4444", "01/31", date(2026, 1, 5), 1, "****1234",
             payment_day=25, credit_limit=500_000, status="lost", lost_at=_kst(2026, 10, 20, 11, 30),
             lost_reason="lost"),
        card("card_005", DEMO_USER_ID, "debit", "5555", "08/29", date(2024, 8, 30), 1, "****1234",
             debit_per_tx=1_000_000, debit_per_day=3_000_000,
             status="terminated", terminated_at=_kst(2026, 8, 30, 10)),
        card("card_900", 2, "debit", "9000", "05/30", date(2025, 5, 1), 5, "****9000",
             debit_per_tx=1_000_000, debit_per_day=3_000_000),
    ])
    db.flush()

    # (id, card, 일시, 가맹점, 금액, 할부)
    approvals = [
        ("tx_205", "card_002", _kst(2026, 8, 10, 15, 40), "삼성전자", 900_000, 3),
        ("tx_201", "card_002", _kst(2026, 9, 12, 13, 10), "이마트", 120_000, 0),
        ("tx_202", "card_002", _kst(2026, 10, 5, 12, 20), "쿠팡", 300_000, 0),
        ("tx_203", "card_002", _kst(2026, 10, 18, 9, 5), "스타벅스 강남점", 12_000, 0),
        ("tx_206", "card_002", _kst(2026, 10, 30, 19, 30), "현대백화점", 600_000, 2),
        ("tx_207", "card_002", _kst(2026, 11, 2, 8, 10), "GS25", 8_000, 0),
        ("tx_401", "card_004", _kst(2026, 10, 15, 20), "올리브영", 45_000, 0),
    ] + [(f"tx_1{n:02d}", "card_001", _kst(2026, 10, n), f"편의점 {n:02d}호점", n * 1_000, 0) for n in range(1, 31)]
    for id_, card_id, when, merchant, amount, inst in approvals:
        db.add(m.CardTransaction(id=id_, card_id=card_id, kind="approval", occurred_at=when, merchant=merchant,
                                 amount=amount, installment_months=inst))
    db.flush()
    db.add(m.CardTransaction(id="tx_204", card_id="card_002", kind="cancel", occurred_at=_kst(2026, 10, 22, 10, 15),
                             merchant="스타벅스 강남점", amount=12_000, original_id="tx_203"))
    db.commit()


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
        m.PlannedOutflow(id="po_001", user_id=DEMO_USER_ID, due_date=due, amount=1_150_000,
                         type="card_bill", ref_type="card", ref_id="card_002"),
    ])
    db.commit()


def _ensure_demo_history(db: Session) -> None:
    """가계부 화면 확인용 가데이터(이미 시드된 DB 에도 한 번만 추가).

    시안의 숫자(이번 달·지난달·지지난달 지출)가 바뀌지 않게, 그 달들은 건드리지 않고 3~5개월 전에만 넣는다.
      · 반복 결제(넷플릭스·통신요금·헬스장): 고정지출 후보와 월별 추이 확인용
      · 월급 입금: 수입 표시와 '수입 대비 지출' 확인용 (잔액은 그대로 두고 내역만 추가)
    """
    if db.get(m.CardTransaction, "ctx_d01"):
        return
    today = date.today()
    recurring = [("넷플릭스", 17_000, "기타", 15), ("통신요금", 55_000, "생활", 20), ("헬스장", 45_000, "생활", 10)]
    # 그 밖의 소비는 달마다 금액이 달라서 고정지출 후보로 잡히지 않는다(추이 그래프만 채운다)
    extra = {
        3: [("마트 장보기", 140_000, "장보기", 6), ("주말 외식", 62_000, "외식", 12), ("교통비", 38_000, "교통", 18)],
        4: [("마트 장보기", 118_000, "장보기", 6), ("주말 외식", 91_000, "외식", 12), ("교통비", 45_000, "교통", 18), ("옷 쇼핑", 130_000, "쇼핑", 22)],
        5: [("마트 장보기", 165_000, "장보기", 6), ("주말 외식", 48_000, "외식", 12), ("교통비", 29_000, "교통", 18)],
    }
    n = 0
    for back in (3, 4, 5):
        first = _month_ago(today, back)
        for merchant, amount, cat, day in recurring + extra[back]:
            n += 1
            id_ = f"ctx_d{n:02d}"
            db.add(m.CardTransaction(id=id_, card_id=LEDGER_DEMO_CARD, kind="approval", merchant=merchant, amount=amount,
                                     occurred_at=datetime(first.year, first.month, day, 12)))
            db.flush()
            db.add(m.LedgerTxCategory(card_transaction_id=id_, user_id=DEMO_USER_ID, category=cat))
    # 월급: 지난 5개월은 25일, 이번 달은 1일 입금
    primary = db.get(m.Account, 1)
    paydays = [_month_ago(today, b).replace(day=25) for b in (5, 4, 3, 2, 1)] + [today.replace(day=1)]
    for day in paydays:
        db.add(m.Transaction(account_id=1, type="deposit", amount=2_800_000,
                             balance_after=primary.balance if primary else 0, counterparty_name="AIM 주식회사",
                             memo="월급", created_at=datetime(day.year, day.month, day.day, 9)))
    db.commit()


def _ensure_demo_sync(db: Session) -> None:
    """카드·계좌 연동 확인용 가데이터(한 번만 추가).

    · 분류가 없는 카드 거래(카드 서비스가 쌓은 것처럼): 가계부가 사용처 이름으로 자동 분류하는지 확인용. 3~5개월 전에만 넣어
      시안의 이번 달·지난달 숫자는 그대로 둔다.
    · 계좌 출금·이체: 이번 달 '계좌 출금·이체' 목록 확인용(예산 계산에는 안 들어가고, 잔액은 그대로 둔다).
    """
    if db.get(m.CardTransaction, "ctx_s01"):
        return
    today = date.today()
    raw = [("스타벅스 강남점", 6_500, 8), ("쿠팡이츠", 23_000, 11), ("GS25 편의점", 4_800, 14),
           ("카카오T 택시", 12_400, 16), ("올리브영", 31_000, 19), ("동네 소고기집", 48_000, 23)]
    n = 0
    for back in (3, 4, 5):
        first = _month_ago(today, back)
        for k, (merchant, amount, day) in enumerate(raw):
            n += 1
            # 달마다 금액을 조금씩 달리해서 '고정지출'로 잡히지 않게 한다(고정지출은 넷플릭스·통신요금·헬스장 가데이터가 맡는다)
            varied = int(amount * (1 + 0.25 * ((back + k) % 3))) // 100 * 100
            db.add(m.CardTransaction(id=f"ctx_s{n:02d}", card_id=LEDGER_DEMO_CARD, kind="approval", merchant=merchant,
                                     amount=varied, occurred_at=datetime(first.year, first.month, day, 13)))
    outflows = [("월세 이체", "transfer_out", 500_000, 2), ("친구 정산", "transfer_out", 35_000, 3), ("관리비 이체", "transfer_out", 100_000, 4)]
    primary = db.get(m.Account, 1)
    for who, type_, amount, day in outflows:
        if day <= today.day:
            db.add(m.Transaction(account_id=1, type=type_, amount=amount,
                                 balance_after=primary.balance if primary else 0, counterparty_name=who,
                                 memo="가데이터", created_at=datetime(today.year, today.month, day, 15)))
    db.commit()


# 시드 사용자(기획서 4.4). 비밀번호·간편비밀번호는 README 에 적는다(개발용 값).
SEED_USERS = [
    # (id, 아이디, 비밀번호, 이름, 생년월일, 휴대폰, 간편비밀번호)
    (1, "user1", "Test1234!", "김하나", date(1990, 5, 15), "01012345678", "482915"),
    (2, "user2", "Test5678!", "이두리", date(1992, 8, 3), "01023456789", "739204"),
    (3, "user3", "Test9012!", "박세나", date(1995, 12, 20), "01034567890", None),  # 간편비밀번호 미설정
    (4, "user4", "Test3456!", "최아란", date(2008, 6, 1), "01045678901", "264817"),  # 만 19세 미만(카드 신청 자격 테스트, 공통.md 7.1)
]


def _seed_users(db: Session) -> None:
    now = datetime.now().astimezone()
    for uid, login_id, pw, name, birth, phone, pin in SEED_USERS:
        db.add(m.User(id=uid, login_id=login_id, password_hash=hash_secret(pw), name=name, birth_date=birth, phone=phone,
                      simple_pin_hash=hash_secret(pin) if pin else None, pin_set_at=now if pin else None))
    db.flush()
    # id 를 직접 넣었으니 다음 가입이 5번부터 시작하도록 시퀀스를 맞춘다
    db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users))"))


PRODUCTS = [
    # (id, type, 상품명, 설명·유의사항, 금리, 중도해지 금리, 최소 금액, 최대 금액, 최소 기간, 최대 기간, 1인 한도, 저축예금 필요)
    (1, "checking", "우리 저축예금",
     "입금·출금·이체가 자유로운 입출금 통장입니다(참고: 우리 WON통장). 연 0.1%는 표시만 하며 이자는 지급하지 않습니다. 1인 최대 5개, 수수료 없음.",
     "0.10", None, None, None, None, None, 5, False),
    (2, "deposit", "우리 정기예금",
     "목돈을 한 번 맡기고 만기에 원금과 이자를 받는 예금입니다(참고: WON플러스 예금). 1만원~1억원, 1~36개월. 출금은 해지로만 가능하며 "
     "만기 전 해지하면 중도해지 금리(연 1.0%)를 적용합니다. 세전·단리·일할 계산. 우대금리·분할해지·만기 자동 재예치는 지원하지 않습니다.",
     "2.90", "1.00", 10_000, 100_000_000, 1, 36, None, True),
    (3, "savings", "우리 정기적금",
     "매월 정해진 금액을 12개월 납입하는 적금입니다(참고: 우리 WON 적금). 월 1만원~50만원, 1인 1계좌. 매월 납입일에 지정 저축예금에서 "
     "자동이체되며 끄면 직접 납입합니다. 만기 전 해지하면 중도해지 금리(연 1.0%)를 적용합니다. 세전·단리·일할 계산.",
     "3.00", "1.00", 10_000, 500_000, 12, 12, 1, True),
]


def _seed_accounts(db: Session, today: date) -> None:
    """계좌.md 7.4 시드: products 3행, 계좌 1~6(id 고정), user1 거래 내역."""
    for id_, type_, name, desc, rate, early, lo, hi, mo_lo, mo_hi, per_user, req in PRODUCTS:
        db.add(m.Product(id=id_, type=type_, name=name, description=desc, rate=rate, early_close_rate=early,
                         min_amount=lo, max_amount=hi, min_months=mo_lo, max_months=mo_hi, max_per_user=per_user,
                         requires_checking=req))
    db.flush()
    dep_open = add_months(today, -6)
    sav_open = add_months(today, -2) - timedelta(days=7)  # 3회차까지 냈고 4회차 납입일은 아직 오지 않는다
    db.add_all([
        m.Account(id=1, user_id=1, product_id=1, account_no="1002-123-451234", balance=1_500_000, rate="0.10",
                  opened_at=add_months(today, -12), is_primary=True),
        m.Account(id=2, user_id=1, product_id=1, account_no="1002-123-455678", alias="생활비", balance=500_000,
                  rate="0.10", opened_at=add_months(today, -8)),
        m.Account(id=3, user_id=1, product_id=2, account_no="1002-223-460003", balance=3_000_000, rate="2.90",
                  term_months=12, linked_account_id=1, opened_at=dep_open, maturity_date=add_months(dep_open, 12)),
        m.Account(id=4, user_id=1, product_id=3, account_no="1002-323-460004", balance=600_000, rate="3.00",
                  term_months=12, monthly_amount=200_000, payment_day=min(sav_open.day, 28), paid_count=3,
                  auto_pay=True, linked_account_id=1, opened_at=sav_open, maturity_date=add_months(sav_open, 12)),
        m.Account(id=5, user_id=2, product_id=1, account_no="1002-123-459000", balance=300_000, rate="0.10",
                  opened_at=add_months(today, -6), is_primary=True),
        m.Account(id=6, user_id=4, product_id=1, account_no="1002-123-454010", balance=100_000, rate="0.10",
                  opened_at=add_months(today, -6), is_primary=True),
    ])
    db.flush()
    # 고정 id 로 넣었으니 다음 개설이 7번부터 시작하도록 시퀀스를 맞춘다
    for table in ("products", "accounts"):
        db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))"))
    a1, a2, a3, a4 = (db.get(m.Account, i) for i in (1, 2, 3, 4))

    def tx(acc, type_, amount, balance_after, day, cp=None, name=None, memo=None):
        db.add(m.Transaction(account_id=acc.id, type=type_, amount=amount, balance_after=balance_after,
                             counterparty_account_id=cp.id if cp else None, counterparty_name=name, memo=memo,
                             created_at=datetime.combine(day, time(9), KST)))

    # 대표계좌(1)의 잔액 흐름은 시연용이라 거래 후 잔액은 현재 잔액으로 둔다(가계부 가데이터와 같은 방식)
    for acc in (a1, a2):
        tx(acc, "open", 0, 0, acc.opened_at)
    tx(a2, "deposit", 400_000, 400_000, add_months(today, -7), name="ATM 입금")
    tx(a2, "transfer_in", 100_000, 500_000, today - timedelta(days=10), cp=a1, name="내 계좌 ****1234", memo="생활비")
    tx(a1, "transfer_out", 100_000, a1.balance, today - timedelta(days=10), cp=a2, name="생활비", memo="생활비")
    tx(a1, "transfer_out", 3_000_000, a1.balance, a3.opened_at, cp=a3, name="정기예금 가입")
    tx(a3, "transfer_in", 3_000_000, 3_000_000, a3.opened_at, cp=a1, name="정기예금 가입")
    for k in (1, 2, 3):
        day = a4.opened_at if k == 1 else min(round_due(a4, k), today)
        name = "정기적금 1회차 납입" if k == 1 else f"정기적금 {k}회차 자동이체"
        tx(a1, "transfer_out", 200_000, a1.balance, day, cp=a4, name=name)
        tx(a4, "transfer_in", 200_000, 200_000 * k, day, cp=a1, name=name)
    for acc, amount in ((db.get(m.Account, 5), 300_000), (db.get(m.Account, 6), 100_000)):
        tx(acc, "open", 0, 0, acc.opened_at)
        tx(acc, "deposit", amount, amount, acc.opened_at, name="ATM 입금")


def seed(db: Session) -> None:
    if db.get(m.User, DEMO_USER_ID):
        _ensure_cards(db)
        _ensure_planned_outflows(db)
        _ensure_demo_history(db)
        _ensure_demo_sync(db)
        loan_setup(db, DEMO_USER_ID)
        return
    today = date.today()
    month = today.strftime("%Y-%m")

    _seed_users(db)
    db.flush()
    _seed_accounts(db, today)

    # 카드
    db.add_all([
        m.CardProduct(id="prod_debit_01", type="debit", name="AIM 체크카드", description="생활 영역 캐시백 체크카드"),
        m.CardProduct(id="prod_credit_01", type="credit", name="AIM 신용카드", description="후불 결제 신용카드"),
    ])
    db.flush()
    db.add_all([
        m.Card(id="card_001", user_id=DEMO_USER_ID, product_id="prod_debit_01", name="AIM 체크카드",
               type="debit", number_last4="1111", expiry="03/30", issued_at=date(2025, 3, 10),
               payment_account_id=1, payment_bank_name="AIM Bank", payment_account_masked="****1234",
               debit_per_tx=1_000_000, debit_per_day=3_000_000),
        m.Card(id="card_002", user_id=DEMO_USER_ID, product_id="prod_credit_01", name="AIM 신용카드",
               type="credit", number_last4="2222", expiry="06/30", issued_at=date(2025, 6, 1),
               payment_account_id=2, payment_bank_name="AIM Bank", payment_account_masked="****5678",
               payment_day=25, credit_limit=3_000_000),
    ])
    db.flush()
    _ensure_cards(db)  # 카드 3~5, 900과 카드 거래 (가계부 데모 거래가 카드 5를 참조한다)
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
        db.add(m.CardTransaction(id=id_, card_id=LEDGER_DEMO_CARD, kind="approval",
                                 occurred_at=datetime.combine(day, datetime.min.time()).replace(hour=12),
                                 merchant=merchant, amount=amount))
    db.flush()
    for id_, _, _, _, cat in txs:
        db.add(m.LedgerTxCategory(card_transaction_id=id_, user_id=DEMO_USER_ID, category=cat))

    # 가계부 예산: 월 800,000 / 배달 90,000
    db.add(m.Budget(id="bud_001", user_id=DEMO_USER_ID, month=month, total_amount=800_000,
                    emergency_floor=0))
    db.flush()
    db.add_all([
        m.CategoryBudget(budget_id="bud_001", category="배달", amount=90_000),
        m.LedgerSettings(user_id=DEMO_USER_ID, mode="roast", roast_level=2),
    ])

    db.commit()
    _ensure_planned_outflows(db)
    _ensure_demo_history(db)
    _ensure_demo_sync(db)
    loan_setup(db, DEMO_USER_ID)
