"""계좌 서비스(계좌.md). 라우터와 자연어 도구가 같은 함수를 쓴다(공통.md 9장).

모든 함수는 `user` 를 서버가 세션에서 넣어 준 값으로만 받고, 계좌는 항상 user_id 로 걸러 찾는다(R3·R4).
돈이 움직이는 함수는 한 트랜잭션 안에서 행을 잠근 채 처리하고 끝에서 commit 한다.
`confirm_pin` 은 업무 조건 검사가 끝난 뒤, 실행 직전에 부르는 콜백이다(본인 재확인, 공통.md 4장 처리 순서).
"""
import logging
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from .. import models as m
from ..auth.deps import api_error, validation_error
from .interest import add_months, deposit_interest, savings_interest

log = logging.getLogger("accounts")

BANK_NAME = "AIM Bank"
KST = timezone(timedelta(hours=9))
CHECKING, DEPOSIT, SAVINGS = 1, 2, 3  # products.id (시드로 고정, 계좌.md 7.1)
PRODUCT_ID = {"checking": CHECKING, "deposit": DEPOSIT, "savings": SAVINGS}
PRODUCT_TYPE = {v: k for k, v in PRODUCT_ID.items()}
ACCOUNT_NO_MID = {"checking": "123", "deposit": "223", "savings": "323"}  # 1002-XXX-XXXXXX (공통.md 7.2)
DEPOSIT_LIMIT = 10_000_000
TRANSFER_PER_TX = 5_000_000
TRANSFER_PER_DAY = 10_000_000
CHECKING_MAX = 5
CLOSE_MEMO = "계좌 해지"  # 해지 때 잔액 이전 표시. 1일 이체 한도 합산에서 뺀다
IN_TYPES = ("deposit", "transfer_in", "interest")
OUT_TYPES = ("transfer_out", "card_payment")
PRODUCT_LABEL = {"deposit": "정기예금", "savings": "정기적금"}


def dev_mode() -> bool:
    return os.getenv("APP_ENV") == "dev"


def today_kst() -> date:
    return datetime.now(KST).date()


def mask(account_no: str) -> str:
    return "****" + account_no[-4:]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _kst_iso(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat()


def _kst_day(day: date) -> datetime:
    return datetime.combine(day, time.min, KST)


def _ptype(acc: m.Account) -> str:
    return PRODUCT_TYPE[acc.product_id]


# ───────────── 조회·잠금 ─────────────

def _not_found() -> Exception:
    return api_error(404, "ACCOUNT_NOT_FOUND", "계좌를 찾을 수 없습니다.")


def _state_error(acc: m.Account, message: str) -> Exception:
    return api_error(409, "ACCOUNT_STATE_INVALID", message, currentStatus=acc.status, allowedStatuses=["active"])


def get_owned(db: Session, user_id: int, account_id: int) -> m.Account:
    """내 계좌만 찾는다. 없는 계좌와 타인의 계좌는 똑같이 404 다(R4)."""
    acc = db.scalar(select(m.Account).where(m.Account.id == account_id, m.Account.user_id == user_id))
    if not acc:
        raise _not_found()
    return acc


def _lock(db: Session, *ids: int) -> dict[int, m.Account]:
    """행을 id 순으로 잠그고 최신 값으로 읽는다(동시 이체·데드락 방지, 계좌.md 7장)."""
    rows = db.scalars(select(m.Account).where(m.Account.id.in_(set(ids))).order_by(m.Account.id)
                      .with_for_update().execution_options(populate_existing=True)).all()
    return {a.id: a for a in rows}


def _lock_user(db: Session, user_id: int) -> None:
    """보유 한도·1일 한도 검사가 동시 요청에 뚫리지 않게 사용자 행을 잠근다."""
    db.execute(select(m.User.id).where(m.User.id == user_id).with_for_update())


def _active_checking(acc: m.Account) -> bool:
    return acc.product_id == CHECKING and acc.status == "active"


def _need_checking(acc: m.Account) -> None:
    if acc.product_id != CHECKING:
        raise _state_error(acc, "저축예금 계좌만 가능합니다.")
    if acc.status != "active":
        raise _state_error(acc, "이미 해지된 계좌입니다.")


def _label(db: Session, acc: m.Account, viewer_id: int) -> str:
    """거래 내역에 적는 상대 표시명. 내 계좌면 별명(없으면 끝 4자리), 남의 계좌면 예금주 이름."""
    if acc.user_id == viewer_id:
        return acc.alias or f"내 계좌 {mask(acc.account_no)}"
    return db.get(m.User, acc.user_id).name


def count_active_cards(db: Session, account_id: int) -> int:
    """그 계좌를 결제 계좌로 쓰는 해지 안 된 카드 수(공통.md 8장 인터페이스). 저축예금 해지 검사에 쓴다."""
    return db.scalar(select(func.count()).select_from(m.Card).where(
        m.Card.payment_account_id == account_id, m.Card.status != "terminated")) or 0


# ───────────── 거래 기록 ─────────────

def _tx(db: Session, acc: m.Account, type_: str, amount: int, *, cp: m.Account | None = None,
        name: str | None = None, memo: str | None = None) -> None:
    db.add(m.Transaction(account_id=acc.id, type=type_, amount=amount, balance_after=acc.balance,
                         counterparty_account_id=cp.id if cp else None, counterparty_name=name, memo=memo,
                         created_at=m.now()))


def _move(db: Session, src: m.Account, dst: m.Account, amount: int, src_name: str, dst_name: str,
          memo: str | None = None) -> None:
    """출금 계좌 transfer_out 과 입금 계좌 transfer_in 2건을 같은 트랜잭션에서 기록한다(계좌.md 7장)."""
    src.balance -= amount
    _tx(db, src, "transfer_out", amount, cp=dst, name=dst_name, memo=memo)
    dst.balance += amount
    _tx(db, dst, "transfer_in", amount, cp=src, name=src_name, memo=memo)


# ───────────── 적금 회차 ─────────────

def round_due(acc: m.Account, k: int) -> date:
    """k회차 납입일 = 개설월 + (k − 1)개월의 납입일(계좌.md 5.3). 1회차는 개설할 때 바로 납입한다."""
    return add_months(acc.opened_at.replace(day=1), k - 1).replace(day=acc.payment_day)


def _unpaid_round(acc: m.Account, today: date) -> int | None:
    """납입일이 지났는데 아직 못 낸 가장 이른 회차(없으면 None)."""
    k = acc.paid_count + 1
    return k if k <= acc.term_months and round_due(acc, k) <= today else None


def _paid_this_month(acc: m.Account, today: date) -> bool:
    """다음 회차의 납입일이 다음 달 이후면 이번 달 몫은 이미 낸 것이다(자동이체·수동 구분 없음)."""
    k = acc.paid_count + 1
    if k > acc.term_months:
        return True
    due = round_due(acc, k)
    return (due.year, due.month) > (today.year, today.month)


# ───────────── 이자 ─────────────

def _savings_payments(db: Session, acc: m.Account) -> list[tuple[date, int]]:
    rows = db.execute(select(m.Transaction.created_at, m.Transaction.amount).where(
        m.Transaction.account_id == acc.id, m.Transaction.type == "transfer_in")).all()
    return [(t.astimezone(KST).date(), a) for t, a in rows]


def _close_terms(db: Session, acc: m.Account, today: date) -> tuple[str, float, int]:
    """지금 해지하면: (matured|early, 적용 금리, 세전 이자). 만기 뒤면 약정 금리·만기일까지, 앞이면 중도해지 금리·오늘까지."""
    matured = today >= acc.maturity_date
    rate = acc.rate if matured else db.get(m.Product, acc.product_id).early_close_rate
    end = acc.maturity_date if matured else today
    if acc.product_id == DEPOSIT:
        interest = deposit_interest(acc.balance, rate, acc.opened_at, end)
    else:
        interest = savings_interest(_savings_payments(db, acc), rate, end)
    return ("matured" if matured else "early"), float(rate), interest


def get_interest(db: Session, user: m.User, account_id: int) -> dict:
    """예적금 이자(ACC-12): 지금까지 쌓인 이자, 만기 예상 이자, 지금 해지 시 받을 이자. 세전."""
    acc = get_owned(db, user.id, account_id)
    res = _interest(db, acc, today_kst())
    if res is None:
        raise _state_error(acc, "진행 중인 예적금 계좌만 조회할 수 있습니다.")
    return res


def _interest(db: Session, acc: m.Account, today: date) -> dict | None:
    if acc.product_id == CHECKING or acc.status != "active":
        return None
    end = min(today, acc.maturity_date)
    if acc.product_id == DEPOSIT:
        accrued = deposit_interest(acc.balance, acc.rate, acc.opened_at, end)
        at_maturity = deposit_interest(acc.balance, acc.rate, acc.opened_at, acc.maturity_date)
    else:
        pays = _savings_payments(db, acc)
        accrued = savings_interest(pays, acc.rate, end)
        # 만기 예상: 아직 안 낸 회차도 납입일에 낸다고 보고 계산한다
        future = [(round_due(acc, k), acc.monthly_amount) for k in range(acc.paid_count + 1, acc.term_months + 1)]
        at_maturity = savings_interest(pays + future, acc.rate, acc.maturity_date)
    kind, rate, interest = _close_terms(db, acc, today)
    return {"accrued": accrued, "atMaturity": at_maturity,
            "closeNow": {"kind": kind, "rate": rate, "interest": interest, "principal": acc.balance,
                         "total": acc.balance + interest}}


# ───────────── 응답 모양 ─────────────

def account_out(db: Session, acc: m.Account, *, detail: bool = False) -> dict:
    """계좌 응답. 전체 계좌번호는 상세에서만 내려준다(공통.md 6장). 해당 없는 값은 null."""
    product = db.get(m.Product, acc.product_id)
    ptype = _ptype(acc)
    out = {
        "accountId": acc.id, "bankName": BANK_NAME, "accountMasked": mask(acc.account_no), "balance": acc.balance,
        "productType": ptype, "productName": product.name, "status": acc.status, "alias": acc.alias,
        "isPrimary": acc.is_primary, "rate": float(acc.rate), "openedAt": _iso(acc.opened_at),
        "maturityDate": _iso(acc.maturity_date), "termMonths": acc.term_months, "monthlyAmount": acc.monthly_amount,
        "paymentDay": acc.payment_day, "paidCount": acc.paid_count if ptype == "savings" else None,
        "autoPay": acc.auto_pay if ptype == "savings" else None,
    }
    if not detail:
        return out
    today = today_kst()
    active = acc.status == "active"
    linked = db.get(m.Account, acc.linked_account_id) if acc.linked_account_id else None
    out.update({
        "accountNo": acc.account_no,
        "earlyCloseRate": float(product.early_close_rate) if product.early_close_rate is not None else None,
        "linkedAccountId": acc.linked_account_id, "linkedAccountMasked": mask(linked.account_no) if linked else None,
        "closedAt": _kst_iso(acc.closed_at) if acc.closed_at else None,
        "interest": _interest(db, acc, today),
        "isMatured": ptype != "checking" and active and today >= acc.maturity_date,
        "unpaidRound": _unpaid_round(acc, today) if ptype == "savings" and active else None,
        "nextDueDate": _iso(round_due(acc, acc.paid_count + 1)) if ptype == "savings" and active and acc.paid_count < acc.term_months else None,
        "paidThisMonth": _paid_this_month(acc, today) if ptype == "savings" and active else None,
        "devTools": dev_mode(),
    })
    return out


def get_account(db: Session, user: m.User, account_id: int) -> dict:
    return account_out(db, get_owned(db, user.id, account_id), detail=True)


def list_accounts(db: Session, user: m.User, *, status: str = "active", purpose: str | None = None) -> dict:
    """내 계좌 목록(ACC-04). purpose=card_payment 면 저축예금이고 active 인 것만(카드 파트, 공통.md 8장)."""
    q = select(m.Account).where(m.Account.user_id == user.id)
    if purpose == "card_payment":
        q = q.where(m.Account.product_id == CHECKING, m.Account.status == "active")
    elif purpose is not None:
        raise validation_error("purpose", "INVALID_ENUM", "허용되지 않은 값입니다.")
    elif status == "closed":
        q = q.where(m.Account.status != "active")
    else:
        q = q.where(m.Account.status == "active")
    q = q.order_by(m.Account.closed_at.desc()) if status == "closed" and purpose is None else \
        q.order_by(m.Account.is_primary.desc(), m.Account.product_id, m.Account.id)
    accounts = db.scalars(q).all()
    return {"totalBalance": sum(a.balance for a in accounts if a.status == "active"),
            "items": [account_out(db, a) for a in accounts]}


def get_balance(db: Session, user: m.User) -> dict:
    """자연어 acc.balance: 저축예금 합계와 계좌별 잔액(예적금은 원금)."""
    res = list_accounts(db, user)
    res["checkingTotal"] = sum(a["balance"] for a in res["items"] if a["productType"] == "checking")
    return res


def list_products(db: Session) -> dict:
    rows = db.scalars(select(m.Product).order_by(m.Product.id)).all()
    return {"items": [{
        "id": p.id, "type": p.type, "name": p.name, "description": p.description, "rate": float(p.rate),
        "earlyCloseRate": float(p.early_close_rate) if p.early_close_rate is not None else None,
        "minAmount": p.min_amount, "maxAmount": p.max_amount, "minMonths": p.min_months,
        "maxMonths": p.max_months, "maxPerUser": p.max_per_user, "requiresChecking": p.requires_checking,
    } for p in rows]}


# ───────────── 거래 내역 ─────────────

def get_transactions(db: Session, user: m.User, account_id: int, *, period: str = "1m", date_from: date | None = None,
                     date_to: date | None = None, type_: str = "all", page: int = 1, size: int = 20) -> dict:
    """거래 내역(ACC-06): 기간·입금/출금 필터, 최신순, 페이지당 20건."""
    acc = get_owned(db, user.id, account_id)
    today = today_kst()
    if period == "custom":
        if not date_from:
            raise validation_error("from", "REQUIRED", "시작일을 입력해 주세요.")
        date_to = date_to or today
        if date_from > date_to:
            raise validation_error("from", "FROM_AFTER_TO", "시작일이 종료일보다 늦습니다.")
    else:
        date_to = today
        date_from = {"1w": today - timedelta(days=7), "1m": add_months(today, -1), "3m": add_months(today, -3)}[period]
    q = select(m.Transaction).where(
        m.Transaction.account_id == acc.id, m.Transaction.created_at >= _kst_day(date_from),
        m.Transaction.created_at < _kst_day(date_to + timedelta(days=1)))
    if type_ == "deposit":
        q = q.where(m.Transaction.type.in_(IN_TYPES))
    elif type_ == "withdraw":
        q = q.where(m.Transaction.type.in_(OUT_TYPES))
    rows = db.scalars(q.order_by(m.Transaction.created_at.desc(), m.Transaction.id.desc())
                      .offset((page - 1) * size).limit(size + 1)).all()
    return {"page": page, "hasNext": len(rows) > size, "items": [{
        "id": t.id, "type": t.type, "direction": "in" if t.type in IN_TYPES else "out" if t.type in OUT_TYPES else None,
        "amount": t.amount, "balanceAfter": t.balance_after, "counterpartyName": t.counterparty_name,
        "memo": t.memo, "createdAt": _kst_iso(t.created_at)} for t in rows[:size]]}


# ───────────── 개설 ─────────────

def _new_account_no(db: Session, ptype: str) -> str:
    for _ in range(20):
        no = f"1002-{ACCOUNT_NO_MID[ptype]}-{random.randint(0, 999_999):06d}"
        if not db.scalar(select(m.Account.id).where(m.Account.account_no == no)):
            return no
    raise api_error(500, "INTERNAL_ERROR", "계좌번호를 만들지 못했습니다.")


def _range(field: str, value, lo: int, hi: int, unit: str = "") -> None:
    if value is None:
        raise validation_error(field, "REQUIRED", "값을 입력해 주세요.")
    if not lo <= value <= hi:
        raise validation_error(field, "OUT_OF_RANGE", f"{lo:,}{unit} 이상 {hi:,}{unit} 이하로 입력해 주세요.")


def open_account(db: Session, user: m.User, product_type: str, *, agreed: bool, alias: str | None = None,
                 is_primary: bool = False, amount: int | None = None, term_months: int | None = None,
                 monthly_amount: int | None = None, payment_day: int | None = None, auto_pay: bool = True,
                 linked_account_id: int | None = None) -> dict:
    """계좌 개설(ACC-02·03). 가입 조건 → 설정 범위 → 출금 계좌 잔액 순으로 검사한 뒤 만든다(계좌.md 5.1)."""
    product = db.scalar(select(m.Product).where(m.Product.type == product_type))
    if not product:
        raise api_error(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다.")
    if not agreed:
        raise validation_error("agreed", "MUST_BE_TRUE", "약관에 동의해 주세요.")
    _lock_user(db, user.id)
    today = today_kst()
    mine = db.scalars(select(m.Account).where(m.Account.user_id == user.id, m.Account.status == "active")).all()
    same = [a for a in mine if a.product_id == product.id]
    if product.max_per_user is not None and len(same) >= product.max_per_user:
        raise api_error(409, "ACCOUNT_COUNT_LIMIT_EXCEEDED", "더 이상 가입할 수 없습니다." if product_type == "checking"
                        else "정기적금은 1인 1계좌만 가입할 수 있습니다.", productType=product_type,
                        current=len(same), max=product.max_per_user)
    if product.requires_checking and not any(_active_checking(a) for a in mine):
        raise api_error(422, "CHECKING_REQUIRED", "저축예금을 먼저 개설해 주세요.")

    need = 0
    if product_type == "checking":
        if alias is not None and len(alias) > 20:
            raise validation_error("alias", "TOO_LONG", "별명은 20자 이하로 입력해 주세요.")
    else:
        if product_type == "deposit":
            _range("amount", amount, product.min_amount, product.max_amount, "원")
            _range("termMonths", term_months, product.min_months, product.max_months, "개월")
            need = amount
        else:
            _range("monthlyAmount", monthly_amount, product.min_amount, product.max_amount, "원")
            _range("paymentDay", payment_day, 1, 28, "일")
            term_months, need = product.max_months, monthly_amount  # 적금 기간은 12개월 고정
        if linked_account_id is None:
            raise validation_error("linkedAccountId", "REQUIRED", "출금 계좌를 선택해 주세요.")
        get_owned(db, user.id, linked_account_id)
        linked = _lock(db, linked_account_id)[linked_account_id]
        _need_checking(linked)
        if linked.balance < need:
            raise api_error(422, "INSUFFICIENT_BALANCE", "출금 계좌 잔액이 부족합니다.", balance=linked.balance, required=need)

    primary_wanted = False
    if product_type == "checking":
        old = [a for a in same if a.is_primary]
        primary_wanted = not old or is_primary  # 첫 계좌는 자동 대표
        for a in old if primary_wanted else []:
            a.is_primary = False
        db.flush()  # 대표계좌는 사용자당 1개라서 옛 대표를 먼저 내린다
    acc = m.Account(
        user_id=user.id, product_id=product.id, account_no=_new_account_no(db, product_type), alias=alias or None,
        balance=0, rate=product.rate, term_months=term_months if product_type != "checking" else None,
        monthly_amount=monthly_amount if product_type == "savings" else None,
        payment_day=payment_day if product_type == "savings" else None, paid_count=0,
        auto_pay=auto_pay if product_type == "savings" else True,
        linked_account_id=linked_account_id if product_type != "checking" else None, opened_at=today,
        maturity_date=add_months(today, term_months) if product_type != "checking" else None,
        status="active", is_primary=primary_wanted)
    db.add(acc)
    db.flush()
    if product_type == "checking":
        _tx(db, acc, "open", 0)
    else:
        if product_type == "savings":
            acc.paid_count = 1
        name = f"{PRODUCT_LABEL[product_type]} 가입" if product_type == "deposit" else "정기적금 1회차 납입"
        # 출금(저축예금 transfer_out) → 입금(새 계좌 transfer_in) 2건
        _move(db, linked, acc, need, name, name)
    db.commit()
    return account_out(db, acc, detail=True)


# ───────────── 입금 ─────────────

def deposit(db: Session, user: m.User, account_id: int, amount: int) -> dict:
    """시연용 현금 입금(ACC-07, 저축예금만)."""
    get_owned(db, user.id, account_id)
    acc = _lock(db, account_id)[account_id]
    _need_checking(acc)
    if amount <= 0:
        raise validation_error("amount", "OUT_OF_RANGE", "1원 이상 입력해 주세요.")
    if amount > DEPOSIT_LIMIT:
        raise api_error(422, "DEPOSIT_LIMIT_EXCEEDED", f"1회 입금 한도는 {DEPOSIT_LIMIT:,}원입니다.", max=DEPOSIT_LIMIT)
    acc.balance += amount
    _tx(db, acc, "deposit", amount, name="ATM 입금")
    db.commit()
    return {"accountId": acc.id, "amount": amount, "balance": acc.balance}


# ───────────── 이체 ─────────────

def _find_target(db: Session, account_no: str) -> m.Account:
    acc = db.scalar(select(m.Account).where(m.Account.account_no == account_no.strip()))
    if not acc or not _active_checking(acc):
        raise api_error(422, "TRANSFER_TARGET_INVALID", "이체할 수 없는 계좌입니다.")
    return acc


def lookup_recipient(db: Session, user: m.User, account_no: str) -> dict:
    """계좌번호로 예금주 이름을 확인한다(ACC-10). 저축예금이 아니거나 해지된 계좌는 이체할 수 없다."""
    acc = _find_target(db, account_no)
    return {"bankName": BANK_NAME, "accountMasked": mask(acc.account_no), "ownerName": db.get(m.User, acc.user_id).name,
            "isMine": acc.user_id == user.id}


def _transferred_today(db: Session, user_id: int, day: date) -> int:
    """오늘(KST) 이체한 합계: 내 저축예금에서 나가 다른 저축예금으로 간 transfer_out(계좌.md 7.4)."""
    me, cp = aliased(m.Account), aliased(m.Account)
    start = _kst_day(day)
    return int(db.scalar(
        select(func.coalesce(func.sum(m.Transaction.amount), 0))
        .join(me, me.id == m.Transaction.account_id).join(cp, cp.id == m.Transaction.counterparty_account_id)
        .where(me.user_id == user_id, me.product_id == CHECKING, cp.product_id == CHECKING,
               m.Transaction.type == "transfer_out", or_(m.Transaction.memo.is_(None), m.Transaction.memo != CLOSE_MEMO),
               m.Transaction.created_at >= start, m.Transaction.created_at < start + timedelta(days=1))) or 0)


def transfer(db: Session, user: m.User, from_account_id: int, amount: int, *, to_account_id: int | None = None,
             to_account_no: str | None = None, memo: str | None = None,
             confirm_pin: Callable[[], None] | None = None) -> dict:
    """저축예금 간 이체(ACC-09·10). 받는 계좌는 내 계좌 id 또는 계좌번호 중 하나."""
    if (to_account_id is None) == (to_account_no is None):
        raise validation_error("toAccountNo", "REQUIRED", "받는 계좌를 하나만 지정해 주세요.")
    if amount <= 0:
        raise validation_error("amount", "OUT_OF_RANGE", "1원 이상 입력해 주세요.")
    get_owned(db, user.id, from_account_id)  # 출금 계좌는 반드시 내 계좌(AF-14)
    dst = get_owned(db, user.id, to_account_id) if to_account_id is not None else _find_target(db, to_account_no)
    if dst.id == from_account_id:
        raise api_error(422, "SAME_ACCOUNT", "출금 계좌와 입금 계좌가 같습니다.")
    _lock_user(db, user.id)
    locked = _lock(db, from_account_id, dst.id)
    src, dst = locked[from_account_id], locked[dst.id]
    _need_checking(src)
    if not _active_checking(dst):
        raise api_error(422, "TRANSFER_TARGET_INVALID", "이체할 수 없는 계좌입니다.")
    if amount > TRANSFER_PER_TX:
        raise api_error(422, "TRANSFER_LIMIT_PER_TX", f"1회 이체 한도는 {TRANSFER_PER_TX:,}원입니다.", max=TRANSFER_PER_TX)
    used = _transferred_today(db, user.id, today_kst())
    if used + amount > TRANSFER_PER_DAY:
        raise api_error(422, "TRANSFER_LIMIT_PER_DAY", f"1일 이체 한도는 {TRANSFER_PER_DAY:,}원입니다.",
                        max=TRANSFER_PER_DAY, used=used)
    if src.balance < amount:
        raise api_error(422, "INSUFFICIENT_BALANCE", "잔액이 부족합니다.", balance=src.balance, required=amount)
    if confirm_pin:
        confirm_pin()
    owner = db.get(m.User, dst.user_id).name
    _move(db, src, dst, amount, _label(db, src, dst.user_id), _label(db, dst, user.id), memo or None)
    db.commit()
    return {"fromAccountId": src.id, "fromAccountMasked": mask(src.account_no), "toAccountMasked": mask(dst.account_no),
            "toOwnerName": owner, "amount": amount, "memo": memo or None, "balance": src.balance,
            "createdAt": _kst_iso(m.now())}


def recent_accounts(db: Session, user: m.User) -> dict:
    """최근 이체한 계좌 5건(ACC-11). 별도 테이블 없이 transfer_out 에서 만든다."""
    me, cp = aliased(m.Account), aliased(m.Account)
    last = func.max(m.Transaction.created_at)
    rows = db.execute(
        select(cp, m.User.name).select_from(m.Transaction)
        .join(me, me.id == m.Transaction.account_id).join(cp, cp.id == m.Transaction.counterparty_account_id)
        .join(m.User, m.User.id == cp.user_id)
        .where(me.user_id == user.id, me.product_id == CHECKING, cp.product_id == CHECKING, cp.status == "active",
               m.Transaction.type == "transfer_out", or_(m.Transaction.memo.is_(None), m.Transaction.memo != CLOSE_MEMO))
        .group_by(cp.id, m.User.name).order_by(last.desc()).limit(5)).all()
    return {"items": [{"accountNo": a.account_no, "bankName": BANK_NAME, "accountMasked": mask(a.account_no),
                       "ownerName": name, "isMine": a.user_id == user.id} for a, name in rows]}


def list_favorites(db: Session, user: m.User) -> dict:
    rows = db.scalars(select(m.FavoriteAccount).where(m.FavoriteAccount.user_id == user.id)
                      .order_by(m.FavoriteAccount.id.desc())).all()
    return {"items": [_fav_out(f) for f in rows]}


def _fav_out(f: m.FavoriteAccount) -> dict:
    return {"id": f.id, "accountNo": f.account_no, "bankName": BANK_NAME, "accountMasked": mask(f.account_no),
            "displayName": f.display_name}


def add_favorite(db: Session, user: m.User, account_no: str, display_name: str | None) -> dict:
    target = _find_target(db, account_no)
    fav = db.scalar(select(m.FavoriteAccount).where(m.FavoriteAccount.user_id == user.id,
                                                    m.FavoriteAccount.account_no == target.account_no))
    if not fav:  # 이미 등록했으면 그대로 돌려준다
        fav = m.FavoriteAccount(user_id=user.id, account_no=target.account_no,
                                display_name=display_name or db.get(m.User, target.user_id).name)
        db.add(fav)
        db.commit()
    return _fav_out(fav)


def delete_favorite(db: Session, user: m.User, favorite_id: int) -> None:
    fav = db.scalar(select(m.FavoriteAccount).where(m.FavoriteAccount.id == favorite_id,
                                                    m.FavoriteAccount.user_id == user.id))
    if not fav:
        raise api_error(404, "NOT_FOUND", "찾을 수 없습니다.")
    db.delete(fav)
    db.commit()


# ───────────── 적금 납입 · 자동이체 ─────────────

def _pay_round(db: Session, acc: m.Account, linked: m.Account, label: str) -> None:
    n = acc.paid_count + 1
    name = f"정기적금 {n}회차 {label}"
    _move(db, linked, acc, acc.monthly_amount, name, name)
    acc.paid_count = n


def pay_savings(db: Session, user: m.User, account_id: int) -> dict:
    """적금 수동 납입(ACC-08). 이번 달 몫을 이미 냈으면(자동이체 포함) 거부한다."""
    acc = get_owned(db, user.id, account_id)
    if acc.product_id != SAVINGS:
        raise _state_error(acc, "정기적금 계좌만 납입할 수 있습니다.")
    locked = _lock(db, acc.linked_account_id, acc.id)
    acc, linked = locked[acc.id], locked[acc.linked_account_id]
    if acc.status != "active":
        raise _state_error(acc, "이미 해지된 계좌입니다.")
    if acc.paid_count >= acc.term_months:
        raise api_error(409, "SAVINGS_COMPLETED", "12회차를 모두 납입했습니다.")
    if _paid_this_month(acc, today_kst()):
        raise api_error(409, "SAVINGS_ALREADY_PAID", "이번 달은 납입이 완료되었습니다.")
    if linked.balance < acc.monthly_amount:
        raise api_error(422, "INSUFFICIENT_BALANCE", "출금 계좌 잔액이 부족합니다.", balance=linked.balance,
                        required=acc.monthly_amount)
    _pay_round(db, acc, linked, "납입")
    db.commit()
    return {"accountId": acc.id, "paidCount": acc.paid_count, "amount": acc.monthly_amount, "balance": acc.balance}


def set_auto_pay(db: Session, user: m.User, account_id: int, enabled: bool) -> dict:
    """자동이체 켜기·끄기. 돈이 움직이지 않아 본인 재확인은 없다(계좌.md 8장)."""
    acc = get_owned(db, user.id, account_id)
    if acc.product_id != SAVINGS or acc.status != "active":
        raise _state_error(acc, "진행 중인 정기적금만 설정할 수 있습니다.")
    acc.auto_pay = enabled
    db.commit()
    return account_out(db, acc, detail=True)


def run_auto_pay(db: Session, today: date | None = None) -> int:
    """자동이체 배치(계좌.md 5.3): 납입일이 지났고 안 낸 회차를 낸다. 잔액이 모자라면 그 회차는 미납으로 두고 다음 실행에서 다시 시도한다."""
    today = today or today_kst()
    ids = db.scalars(select(m.Account.id).where(m.Account.product_id == SAVINGS, m.Account.status == "active",
                                                m.Account.auto_pay.is_(True))).all()
    paid = 0
    for aid in ids:
        try:
            acc = db.get(m.Account, aid)
            locked = _lock(db, acc.linked_account_id, aid)
            acc, linked = locked[aid], locked[acc.linked_account_id]
            while (acc.status == "active" and acc.auto_pay and _unpaid_round(acc, today)
                   and linked.balance >= acc.monthly_amount):
                _pay_round(db, acc, linked, "자동이체")
                paid += 1
            db.commit()
        except Exception:  # 한 계좌의 실패가 다른 계좌를 막지 않게 한다
            db.rollback()
            log.exception("자동이체 실패 account_id=%s", aid)
    return paid


# ───────────── 해지 ─────────────

def _close_blocker(db: Session, acc: m.Account) -> tuple[int, str, str] | None:
    """저축예금을 해지할 수 없게 하는 이유(HTTP, code, message). 없으면 None."""
    if db.scalar(select(func.count()).select_from(m.Account).where(
            m.Account.linked_account_id == acc.id, m.Account.status == "active")):
        return 409, "ACCOUNT_LINKED_SAVINGS", "연결된 예적금이 있어 해지할 수 없습니다."
    if count_active_cards(db, acc.id):
        return 409, "ACCOUNT_LINKED_CARD", "연결된 카드가 있어 해지할 수 없습니다."
    return None


def preview_close(db: Session, user: m.User, account_id: int) -> dict:
    """해지 미리 보기(ACC-14·15, A-12). 예적금은 해지 예상 이자, 저축예금은 해지 가능 여부와 잔액."""
    acc = get_owned(db, user.id, account_id)
    if acc.status != "active":
        raise _state_error(acc, "이미 해지된 계좌입니다.")
    today = today_kst()
    if acc.product_id == CHECKING:
        b = _close_blocker(db, acc)
        return {"productType": "checking", "balance": acc.balance,
                "blocker": {"code": b[1], "message": b[2]} if b else None}
    kind, rate, interest = _close_terms(db, acc, today)
    return {"productType": _ptype(acc), "kind": kind, "principal": acc.balance, "openedAt": _iso(acc.opened_at),
            "maturityDate": _iso(acc.maturity_date), "elapsedDays": (today - acc.opened_at).days, "appliedRate": rate,
            "contractRate": float(acc.rate), "interest": interest, "total": acc.balance + interest,
            "receivingAccountId": acc.linked_account_id}


def close_account(db: Session, user: m.User, account_id: int, *, receiving_account_id: int | None = None,
                  confirm_pin: Callable[[], None] | None = None) -> dict:
    """해지(ACC-14·15). 예적금은 원금+이자를 받을 저축예금으로, 저축예금은 잔액을 다른 저축예금으로 옮긴 뒤 해지한다."""
    acc = get_owned(db, user.id, account_id)
    if acc.status != "active":
        raise _state_error(acc, "이미 해지된 계좌입니다.")
    today = today_kst()
    is_checking = acc.product_id == CHECKING
    if is_checking:
        b = _close_blocker(db, acc)
        if b:
            raise api_error(b[0], b[1], b[2])
        if acc.balance > 0 and receiving_account_id is None:
            raise api_error(422, "CLOSE_TARGET_REQUIRED", "받을 저축예금을 선택해 주세요. 없으면 잔액을 0원으로 만든 뒤 해지해 주세요.")
    else:
        receiving_account_id = receiving_account_id or acc.linked_account_id
    if receiving_account_id is not None:
        if receiving_account_id == acc.id:
            raise api_error(422, "SAME_ACCOUNT", "해지할 계좌로는 받을 수 없습니다.")
        get_owned(db, user.id, receiving_account_id)
    if confirm_pin and not is_checking:  # 예적금 해지만 본인 재확인(공통.md 4장)
        confirm_pin()
    locked = _lock(db, acc.id, *([receiving_account_id] if receiving_account_id else []))
    acc = locked[acc.id]
    recv = locked.get(receiving_account_id)
    if acc.status != "active":
        raise _state_error(acc, "이미 해지된 계좌입니다.")
    if recv is not None and not _active_checking(recv):
        raise _state_error(recv, "받을 계좌는 사용 중인 저축예금이어야 합니다.")

    principal, interest, status = acc.balance, 0, "closed"
    if is_checking:
        if recv is not None and principal > 0:
            _move(db, acc, recv, principal, _label(db, acc, user.id), _label(db, recv, user.id), CLOSE_MEMO)
        if acc.is_primary:
            acc.is_primary = False
            db.flush()
            others = db.scalars(select(m.Account).where(
                m.Account.user_id == user.id, m.Account.product_id == CHECKING, m.Account.status == "active",
                m.Account.id != acc.id).order_by(m.Account.id)).all()
            if others:
                heir = recv if recv in others else others[0]
                heir.is_primary = True
    else:
        kind, _rate, interest = _close_terms(db, acc, today)
        status = "matured" if kind == "matured" else "closed_early"
        label = f"{PRODUCT_LABEL[PRODUCT_TYPE[acc.product_id]]} {'만기해지' if kind == 'matured' else '중도해지'}"
        _move(db, acc, recv, principal, label, label)
        if interest > 0:
            recv.balance += interest
            _tx(db, recv, "interest", interest, name=f"{label} 이자")
    acc.status, acc.closed_at = status, m.now()
    _tx(db, acc, "close", 0)
    db.commit()
    return {"accountId": acc.id, "status": status, "principal": principal, "interest": interest,
            "total": principal + interest, "receivingAccountId": receiving_account_id}


# ───────────── 개발 모드 시연 (APP_ENV=dev) ─────────────

def dev_set_maturity(db: Session, user: m.User, account_id: int) -> dict:
    """만기 도래 시뮬레이션: 만기일을 어제로 바꾼다."""
    acc = get_owned(db, user.id, account_id)
    if acc.product_id == CHECKING or acc.status != "active":
        raise _state_error(acc, "진행 중인 예적금만 바꿀 수 있습니다.")
    acc.maturity_date = today_kst() - timedelta(days=1)
    db.commit()
    return account_out(db, acc, detail=True)
