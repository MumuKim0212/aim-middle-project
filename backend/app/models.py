"""docs/db/db-design.md 의 통합 테이블 설계를 SQLAlchemy 모델로 옮긴 것.

공통 규칙: 금액 BIGINT(원) · 회원·계좌 ID 는 BIGINT IDENTITY, 파트 자체 ID 는 'prefix_<시간순 값>' VARCHAR(40) ·
enum 은 VARCHAR + CHECK · 도메인 간 참조(user_id, account_id)는 논리 참조(FK 없음).
"""
import secrets
import time
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id(prefix: str) -> str:
    """사전순 = 생성순이 되는 ID (ms 타임스탬프 16진 + 난수)."""
    return f"{prefix}_{int(time.time() * 1000):012x}{secrets.token_hex(4)}"


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def pk(prefix: str):
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


def ts_created():
    return mapped_column(DateTime(timezone=True), default=now)


def ts_updated():
    return mapped_column(DateTime(timezone=True), default=now, onupdate=now)


Money = BigInteger

# ───────────────────────── 공통 · 계좌 ─────────────────────────


class User(Base):
    """회원. 회원가입·인증 기획서 8.1 users 테이블. 다른 모든 테이블이 user_id 로 이 테이블을 참조한다."""
    __tablename__ = "users"
    # 시드 사용자 id 를 1~3 으로 고정해야 해서 BY DEFAULT 로 둔다(시드 뒤 시퀀스를 맞춘다).
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    login_id: Mapped[str] = mapped_column(String(20), unique=True)  # 소문자로 정규화해 저장
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(30))
    birth_date: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(11))  # 숫자만 저장, 중복 허용
    marketing_agree: Mapped[bool] = mapped_column(Boolean, default=False)
    simple_pin_hash: Mapped[str | None] = mapped_column(Text)  # 간편비밀번호(6자리) 해시. 미설정이면 NULL
    pin_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pin_failed_count: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 재설정으로만 풀린다
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = ts_created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(Base):
    """기기 등록 쿠키. 쿠키 값(무작위 토큰)은 해시만 저장한다. 인증 파트만 읽고 쓴다."""
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    device_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts_created()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_devices_user", "user_id"),)


class Product(Base):
    """상품(dev/account/backend-spec.md 7.1). 3행 고정: 1 저축예금, 2 정기예금, 3 정기적금. 시드로 id 를 고정하므로 BY DEFAULT."""
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    type: Mapped[str] = mapped_column(Text)  # checking | deposit | savings
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    early_close_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    min_amount: Mapped[int | None] = mapped_column(Money)
    max_amount: Mapped[int | None] = mapped_column(Money)
    min_months: Mapped[int | None] = mapped_column(Integer)
    max_months: Mapped[int | None] = mapped_column(Integer)
    max_per_user: Mapped[int | None] = mapped_column(Integer)
    requires_checking: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("type IN ('checking','deposit','savings')", name="ck_products_type"),)


class Account(Base):
    """계좌(dev/account/backend-spec.md 7.2). 시드로 id 1~6 을 고정하므로 BY DEFAULT. 은행명은 컬럼이 아니라 API 상수다."""
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    account_no: Mapped[str] = mapped_column(Text, unique=True)  # 1002-XXX-XXXXXX 평문
    alias: Mapped[str | None] = mapped_column(Text)
    balance: Mapped[int] = mapped_column(Money, default=0)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # 개설 시점에 확정된 연금리
    term_months: Mapped[int | None] = mapped_column(Integer)
    monthly_amount: Mapped[int | None] = mapped_column(Money)
    payment_day: Mapped[int | None] = mapped_column(Integer)
    paid_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_pay: Mapped[bool] = mapped_column(Boolean, default=True)
    linked_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    opened_at: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="active")  # active | matured | closed_early | closed
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance"),
        CheckConstraint("status IN ('active','matured','closed_early','closed')", name="ck_accounts_status"),
        Index("ix_accounts_user_status", "user_id", "status"),
        Index("uq_accounts_primary", "user_id", unique=True, postgresql_where=text("is_primary")),
    )


class Transaction(Base):
    """계좌 거래(dev/account/backend-spec.md 7.3). card_payment 는 이름만 예약한다(결정기록.md 10장). 대출 지급·상환은 ref_type='loan', ref_id=계약번호."""
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    type: Mapped[str] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(Money)  # 양수. open·close 는 0
    balance_after: Mapped[int] = mapped_column(Money)
    counterparty_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    counterparty_name: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(Text)  # 이 거래를 만든 업무(현재 'loan')
    ref_id: Mapped[str | None] = mapped_column(Text)  # 업무 쪽 키(대출은 계약번호)
    created_at: Mapped[datetime] = ts_created()
    __table_args__ = (
        CheckConstraint(
            "type IN ('open','deposit','transfer_in','transfer_out','interest','close','card_payment',"
            "'loan_disbursement','loan_repayment')",
            name="ck_tx_type"),
        CheckConstraint("amount >= 0", name="ck_tx_amount"),
        Index("ix_tx_account_time", "account_id", text("created_at DESC"), text("id DESC")),
        Index("ix_tx_ref", "ref_type", "ref_id"),
    )


class FavoriteAccount(Base):
    __tablename__ = "favorite_accounts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_no: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts_created()
    __table_args__ = (UniqueConstraint("user_id", "account_no", name="uq_fav_user_no"),)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    idem_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts_created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_idem_expires", "expires_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = pk("audit")
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(30))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    actor: Mapped[str | None] = mapped_column(String(40))
    at: Mapped[datetime] = ts_created()
    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id", "at"),)


# ───────────────────────── 카드 ─────────────────────────


class CardProduct(Base):
    __tablename__ = "card_products"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    type: Mapped[str] = mapped_column(String(6))
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("type IN ('credit','debit')", name="ck_cp_type"),)


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = pk("card")
    user_id: Mapped[int] = mapped_column(BigInteger)  # 논리 참조
    product_id: Mapped[str] = mapped_column(ForeignKey("card_products.id"))
    name: Mapped[str] = mapped_column(String(50))
    type: Mapped[str] = mapped_column(String(6))
    number_last4: Mapped[str] = mapped_column(String(4))
    expiry: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(12), default="active")
    issued_at: Mapped[date] = mapped_column(Date)
    payment_account_id: Mapped[int] = mapped_column(BigInteger)  # 논리 참조 → accounts.id
    payment_bank_name: Mapped[str] = mapped_column(String(30))
    payment_account_masked: Mapped[str] = mapped_column(String(20))
    payment_day: Mapped[int | None] = mapped_column(SmallInteger)
    credit_limit: Mapped[int | None] = mapped_column(Money)
    debit_per_tx: Mapped[int | None] = mapped_column(Money)
    debit_per_day: Mapped[int | None] = mapped_column(Money)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_reason: Mapped[str | None] = mapped_column(String(6))
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminated_reason: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[datetime] = ts_updated()
    __table_args__ = (
        CheckConstraint("type IN ('credit','debit')", name="ck_cards_type"),
        CheckConstraint("status IN ('active','suspended','lost','terminated')", name="ck_cards_status"),
        CheckConstraint(
            "(type='credit' AND payment_day IS NOT NULL AND credit_limit IS NOT NULL "
            "AND debit_per_tx IS NULL AND debit_per_day IS NULL) OR "
            "(type='debit' AND payment_day IS NULL AND credit_limit IS NULL "
            "AND debit_per_tx IS NOT NULL AND debit_per_day IS NOT NULL)",
            name="ck_cards_kind_cols",
        ),
        CheckConstraint("payment_day IS NULL OR payment_day BETWEEN 1 AND 28", name="ck_cards_payday"),
        CheckConstraint("(status='suspended') = (suspended_at IS NOT NULL)", name="ck_cards_susp"),
        CheckConstraint("status <> 'lost' OR lost_at IS NOT NULL", name="ck_cards_lost"),
        CheckConstraint("status <> 'terminated' OR terminated_at IS NOT NULL", name="ck_cards_term"),
        CheckConstraint("(lost_at IS NOT NULL) = (lost_reason IS NOT NULL)", name="ck_cards_lost_reason"),
        UniqueConstraint("user_id", "number_last4", name="uq_cards_user_last4"),
        Index("ix_cards_user_status", "user_id", "status"),
    )


class CardStatusHistory(Base):
    __tablename__ = "card_status_history"
    id: Mapped[str] = pk("csh")
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(12))
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    request_id: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (
        CheckConstraint("action IN ('issue','suspend','resume','report_lost','terminate')", name="ck_csh_action"),
        Index("ix_csh_card_time", "card_id", "occurred_at"),
    )


class CardTransaction(Base):
    __tablename__ = "card_transactions"
    id: Mapped[str] = pk("ctx")
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"))
    kind: Mapped[str] = mapped_column(String(8))  # approval | cancel
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    merchant: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(Money)
    installment_months: Mapped[int] = mapped_column(SmallInteger, default=0)
    original_id: Mapped[str | None] = mapped_column(ForeignKey("card_transactions.id"), unique=True)
    __table_args__ = (
        CheckConstraint("kind IN ('approval','cancel')", name="ck_ctx_kind"),
        CheckConstraint("amount > 0", name="ck_ctx_amount"),
        CheckConstraint("installment_months = 0 OR installment_months BETWEEN 2 AND 12", name="ck_ctx_inst"),
        CheckConstraint("kind <> 'approval' OR original_id IS NULL", name="ck_ctx_appr"),
        CheckConstraint(
            "kind <> 'cancel' OR (original_id IS NOT NULL AND installment_months = 0)",
            name="ck_ctx_cancel",
        ),
        Index("ix_ctx_card_time", "card_id", "occurred_at", "id"),
    )


class CardApplication(Base):
    __tablename__ = "card_applications"
    id: Mapped[str] = pk("capp")
    user_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(6))
    product_id: Mapped[str] = mapped_column(ForeignKey("card_products.id"))
    payment_account_id: Mapped[int] = mapped_column(BigInteger)
    payment_day: Mapped[int | None] = mapped_column(SmallInteger)
    income_range: Mapped[str | None] = mapped_column(String(10))
    recipient: Mapped[str] = mapped_column(String(20))
    phone: Mapped[str] = mapped_column(String(13))
    address_line1: Mapped[str] = mapped_column(String(100))
    address_line2: Mapped[str | None] = mapped_column(String(100))
    agree_card_terms: Mapped[bool] = mapped_column(Boolean, default=True)
    agree_privacy: Mapped[bool] = mapped_column(Boolean, default=True)
    agree_credit_inquiry: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(8))  # approved | rejected
    reject_reason: Mapped[str | None] = mapped_column(String(30))
    granted_limit: Mapped[int | None] = mapped_column(Money)
    result_card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_capp_user_time", "user_id", "requested_at"),)


class CardIssueQuota(Base):
    __tablename__ = "card_issue_quota"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(6), primary_key=True)


# ───────────────────────── 가계부 ─────────────────────────


class LedgerTxCategory(Base):
    __tablename__ = "ledger_tx_category"
    card_transaction_id: Mapped[str] = mapped_column(ForeignKey("card_transactions.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(4), default="auto")  # auto | user
    updated_at: Mapped[datetime] = ts_updated()
    __table_args__ = (Index("ix_ltc_user_cat", "user_id", "category"),)


class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[str] = pk("bud")
    user_id: Mapped[int] = mapped_column(BigInteger)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    total_amount: Mapped[int] = mapped_column(Money)
    emergency_floor: Mapped[int] = mapped_column(Money, default=0)
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[datetime] = ts_updated()
    __table_args__ = (UniqueConstraint("user_id", "month", name="uq_budget_user_month"),)


class CategoryBudget(Base):
    __tablename__ = "category_budgets"
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"), primary_key=True)
    category: Mapped[str] = mapped_column(String(20), primary_key=True)
    amount: Mapped[int] = mapped_column(Money)


class PlannedOutflow(Base):
    __tablename__ = "planned_outflows"
    id: Mapped[str] = pk("po")
    user_id: Mapped[int] = mapped_column(BigInteger)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(Money)
    type: Mapped[str] = mapped_column(String(20))  # card_bill|fixed|loan_repayment
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="planned")


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    id: Mapped[str] = pk("pa")
    user_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(Money)
    category: Mapped[str | None] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(String(8))  # allowed | held
    reason: Mapped[str | None] = mapped_column(String(20))  # MONTH_BUDGET|CATEGORY_BUDGET|BALANCE
    over_amount: Mapped[int | None] = mapped_column(Money)
    card_transaction_id: Mapped[str | None] = mapped_column(ForeignKey("card_transactions.id"))
    created_at: Mapped[datetime] = ts_created()
    __table_args__ = (Index("ix_pa_user_time", "user_id", "created_at"),)


class LedgerSettings(Base):
    __tablename__ = "ledger_settings"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), default="basic")  # roast|basic|kind|numbers
    roast_level: Mapped[int] = mapped_column(SmallInteger, default=1)
    updated_at: Mapped[datetime] = ts_updated()


class LedgerGoal(Base):
    """월 저축 목표. 모은 돈은 저장하지 않고 조회 시 계산한다(결제 전 확인에서 보류로 막은 금액)."""
    __tablename__ = "ledger_goals"
    id: Mapped[str] = pk("lgl")
    user_id: Mapped[int] = mapped_column(BigInteger)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    name: Mapped[str] = mapped_column(String(30))
    target_amount: Mapped[int] = mapped_column(Money)
    created_at: Mapped[datetime] = ts_created()
    __table_args__ = (UniqueConstraint("user_id", "month", name="uq_goal_user_month"),
                      CheckConstraint("target_amount > 0", name="ck_goal_target"))


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = pk("chs")
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = ts_created()


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = pk("chm")
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(30))
    context_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = ts_created()


class RagDocument(Base):
    __tablename__ = "rag_documents"
    id: Mapped[str] = pk("rag")
    source_url: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(20))
    chunk_text: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
