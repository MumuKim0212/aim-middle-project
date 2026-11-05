"""개발용 시드 데이터. 카드 기획서 기준 데이터(user_id 1, acc_001/002, card_001/002)를 따른다."""
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .auth.security import hash_secret

DEMO_USER_ID = 1  # user1 (김하나)


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
            db.add(m.CardTransaction(id=id_, card_id="card_002", kind="approval", merchant=merchant, amount=amount,
                                     occurred_at=datetime(first.year, first.month, day, 12)))
            db.flush()
            db.add(m.LedgerTxCategory(card_transaction_id=id_, user_id=DEMO_USER_ID, category=cat))
    # 월급: 지난 5개월은 25일, 이번 달은 1일 입금
    primary = db.get(m.Account, "acc_001")
    paydays = [_month_ago(today, b).replace(day=25) for b in (5, 4, 3, 2, 1)] + [today.replace(day=1)]
    for i, day in enumerate(paydays, 1):
        db.add(m.AccountTransaction(id=f"atx_d{i:02d}", account_id="acc_001", kind="deposit", amount=2_800_000,
                                    balance_after=primary.balance if primary else 0, counterparty="AIM 주식회사",
                                    memo="월급", occurred_at=datetime(day.year, day.month, day.day, 9)))
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
            db.add(m.CardTransaction(id=f"ctx_s{n:02d}", card_id="card_002", kind="approval", merchant=merchant,
                                     amount=varied, occurred_at=datetime(first.year, first.month, day, 13)))
    outflows = [("월세 이체", "transfer_out", 500_000, 2), ("친구 정산", "transfer_out", 35_000, 3), ("ATM 출금", "withdraw", 100_000, 4)]
    primary = db.get(m.Account, "acc_001")
    for i, (who, kind, amount, day) in enumerate(outflows, 1):
        if day <= today.day:
            db.add(m.AccountTransaction(id=f"atx_s{i:02d}", account_id="acc_001", kind=kind, amount=amount,
                                        balance_after=primary.balance if primary else 0, counterparty=who,
                                        memo="가데이터", occurred_at=datetime(today.year, today.month, day, 15)))
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
    # id 를 직접 넣었으니 다음 가입이 4번부터 시작하도록 시퀀스를 맞춘다
    db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users))"))
    # user2: 타인 데이터 접근 차단 테스트용(F-06). 계좌만 하나 둔다.
    db.add(m.Account(id="acc_101", user_id=2, bank_name="AIM Bank", account_no_enc="enc:110-777-100101",
                     account_masked="****0101", balance=300_000, purpose="general", is_primary=True))
    db.add(m.AccountPinState(account_id="acc_101"))
    db.add(m.Account(id="acc_104", user_id=4, bank_name="AIM Bank", account_no_enc="enc:1002-123-454010",
                     account_masked="****4010", balance=100_000, purpose="general", is_primary=True))
    db.add(m.AccountPinState(account_id="acc_104"))


def _ensure_user4(db: Session) -> None:
    """공통.md 7.1: user4(최아란)와 그의 저축예금(7.2의 계좌 6). 이미 시드된 DB 에도 한 번만 넣는다."""
    if db.get(m.User, 4):
        return
    now = datetime.now().astimezone()
    _, login_id, pw, name, birth, phone, pin = SEED_USERS[3]
    db.add(m.User(id=4, login_id=login_id, password_hash=hash_secret(pw), name=name, birth_date=birth, phone=phone,
                  simple_pin_hash=hash_secret(pin), pin_set_at=now))
    db.flush()
    db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users))"))
    db.add(m.Account(id="acc_104", user_id=4, bank_name="AIM Bank", account_no_enc="enc:1002-123-454010",
                     account_masked="****4010", balance=100_000, purpose="general", is_primary=True))
    db.add(m.AccountPinState(account_id="acc_104"))
    db.commit()


def seed(db: Session) -> None:
    if db.get(m.User, DEMO_USER_ID):
        _ensure_user4(db)
        _ensure_planned_outflows(db)
        _ensure_demo_history(db)
        _ensure_demo_sync(db)
        return
    today = date.today()
    month = today.strftime("%Y-%m")

    _seed_users(db)
    db.flush()
    db.add_all([
        m.Account(id="acc_001", user_id=DEMO_USER_ID, bank_name="AIM Bank",
                  account_no_enc="enc:110-123-454821", account_masked="****4821",
                  balance=1_245_000, purpose="general", is_primary=True),
        m.Account(id="acc_002", user_id=DEMO_USER_ID, bank_name="AIM Bank",
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
        m.Card(id="card_001", user_id=DEMO_USER_ID, product_id="prod_debit_01", name="AIM 체크카드",
               type="debit", number_last4="1111", expiry="03/30", issued_at=date(2025, 3, 10),
               payment_account_id="acc_001", payment_bank_name="AIM Bank", payment_account_masked="****4821",
               debit_per_tx=1_000_000, debit_per_day=3_000_000),
        m.Card(id="card_002", user_id=DEMO_USER_ID, product_id="prod_credit_01", name="AIM 신용카드",
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
        db.add(m.LedgerTxCategory(card_transaction_id=id_, user_id=DEMO_USER_ID, category=cat))

    # 가계부 예산: 월 800,000 / 배달 90,000
    db.add(m.Budget(id="bud_001", user_id=DEMO_USER_ID, month=month, total_amount=800_000,
                    emergency_floor=0))
    db.flush()
    db.add_all([
        m.CategoryBudget(budget_id="bud_001", category="배달", amount=90_000),
        m.LedgerSettings(user_id=DEMO_USER_ID, mode="roast", roast_level=2),
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
        db.add(m.LoanApplication(id=app_id, user_id=DEMO_USER_ID, product_type="general", status="contracted"))
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
    _ensure_demo_history(db)
    _ensure_demo_sync(db)
