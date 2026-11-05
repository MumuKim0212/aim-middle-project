"""가계부 API (박의혁).

기준: 가계부_4가지_모드_체험.html 의 계산식을 서버로 옮긴 것. 금액은 전부 정수(원).
member_id 는 인증 세션(current_member)에서만 얻는다.

사용 테이블 (docs/db/db-design.md 5절, 변경 없음)
  card_transactions + ledger_tx_category : 월 지출 / 카테고리별 지출
  budgets + category_budgets             : 월 예산 / 카테고리 예산
  planned_outflows                       : 예정 출금(카드대금) → 예상 잔액
  payment_attempts                       : 결제 전 확인 기록
  ledger_settings                        : 말투·화면 모드

계산
  순지출        = 승인 합계 - 취소 합계 (취소는 원 승인 거래의 카테고리를 따른다)
  남은 예산     = 월 예산 - 순지출
  예상 잔액     = 대표계좌 잔액 - 예정 출금 합계
  위험 단계     = danger : 월 예산/카테고리 예산/예상 잔액 중 하나라도 0 이하
                  caution: 사용률 75% 이상, 또는 카테고리 예산 사용률 80% 이상
                  safe   : 그 외
  결제 전 확인  = 금액이 월 예산 잔여 / 예상 잔액 / 카테고리 예산 잔여 중 하나라도 넘으면 보류
"""
import re
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import models as m
from .db import get_db
from .deps import current_member

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
UNCATEGORIZED = "기타"
CATEGORIES = ["배달", "외식", "장보기", "쇼핑", "교통", "생활", "기타"]
MODES = ("roast", "basic", "kind", "numbers")


def this_month() -> str:
    return date.today().strftime("%Y-%m")


def pct(part: int, whole: int) -> int:
    """정수 퍼센트, 반올림은 half-up (시안의 JS Math.round 와 같다)."""
    return (part * 100 + whole // 2) // whole if whole else 0


def month_range(month: str) -> tuple[date, date]:
    if not MONTH_RE.match(month):
        raise HTTPException(400, "INVALID_MONTH")
    y, mo = int(month[:4]), int(month[5:])
    return date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1)


def category_spent(db: Session, member_id: str, start: date, end: date) -> dict[str, int]:
    """카테고리별 순지출. 취소 거래는 원 승인 거래의 카테고리를 따른다."""
    signed = case((m.CardTransaction.kind == "approval", m.CardTransaction.amount),
                  else_=-m.CardTransaction.amount)
    cat = func.coalesce(m.LedgerTxCategory.category, UNCATEGORIZED).label("cat")
    rows = db.execute(
        select(cat, func.sum(signed))
        .select_from(m.CardTransaction)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(
            m.LedgerTxCategory,
            m.LedgerTxCategory.card_transaction_id == func.coalesce(m.CardTransaction.original_id, m.CardTransaction.id),
        )
        .where(m.Card.member_id == member_id,
               m.CardTransaction.occurred_at >= start,
               m.CardTransaction.occurred_at < end)
        .group_by(cat)
    ).all()
    return {name: int(total) for name, total in rows}


def build_summary(db: Session, member_id: str, month: str) -> dict:
    start, end = month_range(month)
    spent_by_cat = category_spent(db, member_id, start, end)
    spent = sum(spent_by_cat.values())

    budget = db.scalar(select(m.Budget).where(m.Budget.member_id == member_id, m.Budget.month == month))
    total = budget.total_amount if budget else 0
    cat_budgets: dict[str, int] = {}
    if budget:
        cat_budgets = {c.category: c.amount for c in db.scalars(
            select(m.CategoryBudget).where(m.CategoryBudget.budget_id == budget.id))}

    categories = []
    for cat in sorted(set(cat_budgets) | set(spent_by_cat), key=lambda c: CATEGORIES.index(c) if c in CATEGORIES else 99):
        s, b = spent_by_cat.get(cat, 0), cat_budgets.get(cat)
        categories.append({
            "category": cat, "budget": b, "spent": s,
            "remaining": None if b is None else b - s,
            "ratio": None if not b else pct(s, b),
            "over": b is not None and s > b,
        })

    primary = db.scalar(select(m.Account).where(
        m.Account.member_id == member_id, m.Account.is_primary.is_(True), m.Account.status == "active"))
    balance = primary.balance if primary else 0
    planned_rows = db.scalars(
        select(m.PlannedOutflow)
        .where(m.PlannedOutflow.member_id == member_id, m.PlannedOutflow.status == "planned",
               m.PlannedOutflow.due_date >= max(date.today(), start), m.PlannedOutflow.due_date < end)
        .order_by(m.PlannedOutflow.due_date)
    ).all()
    planned_total = sum(p.amount for p in planned_rows)
    expected = balance - planned_total

    remaining = total - spent
    ratio = pct(spent, total)
    over_cat = [c for c in categories if c["budget"] is not None and c["remaining"] <= 0]
    hot_cat = [c for c in categories if c["ratio"] is not None and c["ratio"] >= 80]
    if not budget:
        level = "safe"
    elif remaining <= 0 or over_cat or expected <= 0:
        level = "danger"
    elif ratio >= 75 or hot_cat:
        level = "caution"
    else:
        level = "safe"

    return {
        "month": month,
        "budget": {
            "total": total, "spent": spent, "remaining": remaining, "ratio": ratio,
            "emergencyFloor": budget.emergency_floor if budget else 0, "set": budget is not None,
        },
        "risk": {"level": level, "ratio": ratio,
                 "hotCategories": [c["category"] for c in (over_cat + [h for h in hot_cat if h not in over_cat])]},
        "categories": categories,
        "account": None if not primary else {
            "id": primary.id, "bankName": primary.bank_name, "masked": primary.account_masked},
        "balance": {
            "current": balance, "plannedOutflow": planned_total, "expected": expected,
            "planned": [{"id": p.id, "dueDate": p.due_date.isoformat(), "amount": p.amount, "type": p.type}
                        for p in planned_rows],
        },
    }


@router.get("/summary")
def summary(
    month: str = Query(default_factory=this_month),
    member: m.Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    return build_summary(db, member.id, month)


# ───────────── 결제 전 확인 ─────────────


class PaymentCheckIn(BaseModel):
    amount: int = Field(gt=0, le=10_000_000_000)
    category: str = Field(default=UNCATEGORIZED, max_length=20)
    record: bool = True  # False 면 판정만 하고 payment_attempts 에 남기지 않는다(질문창 미리보기)


REASON_ORDER = ("MONTH_BUDGET", "BALANCE", "CATEGORY_BUDGET")


@router.post("/payment-check")
def payment_check(
    body: PaymentCheckIn,
    member: m.Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    s = build_summary(db, member.id, this_month())
    remaining, expected = s["budget"]["remaining"], s["balance"]["expected"]
    cat = next((c for c in s["categories"] if c["category"] == body.category and c["budget"] is not None), None)
    cat_remaining = cat["remaining"] if cat else None

    limits = {"MONTH_BUDGET": remaining, "BALANCE": expected, "CATEGORY_BUDGET": cat_remaining}
    reasons = [r for r in REASON_ORDER if limits[r] is not None and body.amount > limits[r]]
    result = "held" if reasons else "allowed"
    over = max((body.amount - limits[r] for r in reasons), default=0)

    if body.record:
        db.add(m.PaymentAttempt(
            member_id=member.id, amount=body.amount, category=body.category, result=result,
            reason=reasons[0] if reasons else None, over_amount=over or None))
        db.commit()

    return {
        "result": result,
        "reasons": reasons,
        "limits": limits,
        "overAmount": over,
        "after": {
            "budgetRemaining": remaining - body.amount,
            "expectedBalance": expected - body.amount,
            "categoryRemaining": None if cat_remaining is None else cat_remaining - body.amount,
        },
        "category": body.category,
        "amount": body.amount,
    }


# ───────────── 모드 설정 ─────────────


class SettingsIn(BaseModel):
    mode: str


@router.get("/settings")
def get_settings(member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    row = db.get(m.LedgerSettings, member.id)
    return {"mode": row.mode if row else "basic", "roastLevel": row.roast_level if row else 1}


@router.put("/settings")
def put_settings(body: SettingsIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    if body.mode not in MODES:
        raise HTTPException(400, "INVALID_MODE")
    row = db.get(m.LedgerSettings, member.id)
    if row:
        row.mode = body.mode
    else:
        db.add(m.LedgerSettings(member_id=member.id, mode=body.mode))
    db.commit()
    return {"mode": body.mode}


# ───────────── 소비 내역 ─────────────
#
# 지출 기록은 "모의 카드 승인"이다. 카드 도메인의 card_transactions 에 승인 행을 넣고
# ledger_tx_category(source='user') 에 사용자가 고른 분류를 남긴다. 카드 설계서는 거래를 만드는
# 카드 API가 없다고 했으므로, 가계부 모듈이 직접 쓰는 이 경로는 데모 용도다(팀 합의 필요).
# 'source=user' 행만 삭제할 수 있다(시드 거래는 삭제 불가).


def _prev_month(month: str) -> str:
    y, mo = int(month[:4]), int(month[5:])
    y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    return f"{y:04d}-{mo:02d}"


def _adjust_card_bill(db: Session, member_id: str, card: m.Card, tx_date: date, delta: int) -> None:
    """신용카드 승인은 미결제 카드대금(planned_outflows)을 늘리고, 삭제하면 줄인다.

    기획안 3절: 카드 승인 시점에는 미결제 카드대금이 늘고 계좌 잔액은 실제 출금 때 줄어든다.
    이번 달 거래만 이번 달 예정 출금에 반영한다.
    """
    if card.type != "credit" or tx_date.strftime("%Y-%m") != this_month():
        return
    today = date.today()
    row = db.scalar(
        select(m.PlannedOutflow)
        .where(m.PlannedOutflow.member_id == member_id, m.PlannedOutflow.type == "card_bill",
               m.PlannedOutflow.ref_id == card.id, m.PlannedOutflow.status == "planned",
               m.PlannedOutflow.due_date >= today)
        .order_by(m.PlannedOutflow.due_date)
    )
    if row:
        row.amount = max(0, row.amount + delta)
    elif delta > 0:
        day = min(card.payment_day or 25, 28)
        due = date(today.year, today.month, day)
        if due < today:  # 이번 달 결제일이 지났으면 다음 달
            due = date(today.year + (today.month == 12), today.month % 12 + 1, day)
        db.add(m.PlannedOutflow(member_id=member_id, due_date=due, amount=delta, type="card_bill",
                                ref_type="card", ref_id=card.id))


@router.get("/transactions")
def transactions(
    month: str = Query(default_factory=this_month),
    member: m.Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    start, end = month_range(month)
    cat = func.coalesce(m.LedgerTxCategory.category, UNCATEGORIZED)
    rows = db.execute(
        select(m.CardTransaction, cat, m.LedgerTxCategory.source)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(
            m.LedgerTxCategory,
            m.LedgerTxCategory.card_transaction_id == func.coalesce(m.CardTransaction.original_id, m.CardTransaction.id),
        )
        .where(m.Card.member_id == member.id,
               m.CardTransaction.occurred_at >= start, m.CardTransaction.occurred_at < end)
        .order_by(m.CardTransaction.occurred_at.desc(), m.CardTransaction.id.desc())
    ).all()

    items = [{
        "id": tx.id,
        "date": tx.occurred_at.date().isoformat(),
        "merchant": tx.merchant,
        "category": category,
        "kind": tx.kind,
        # 화면 표시용 부호: 승인은 지출(-), 취소는 환불(+)
        "amount": -tx.amount if tx.kind == "approval" else tx.amount,
        "canDelete": tx.kind == "approval" and source == "user",
    } for tx, category, source in rows]

    now_by_cat = category_spent(db, member.id, start, end)
    prev_start, prev_end = month_range(_prev_month(month))
    prev_spent = sum(category_spent(db, member.id, prev_start, prev_end).values())
    top = max(now_by_cat.items(), key=lambda kv: kv[1], default=(None, 0))
    spent = sum(now_by_cat.values())
    return {
        "month": month,
        "items": items,
        "report": {
            "spent": spent,
            "prevSpent": prev_spent,
            "hasPrev": prev_spent != 0,
            "delta": spent - prev_spent,
            "topCategory": top[0] if top[1] > 0 else None,
            "topAmount": top[1] if top[1] > 0 else 0,
        },
    }


class TxIn(BaseModel):
    date: date
    merchant: str = Field(min_length=1, max_length=30)
    category: str
    amount: int = Field(gt=0, le=100_000_000)


@router.post("/transactions", status_code=201)
def add_transaction(body: TxIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    merchant = body.merchant.strip()
    if not merchant:
        raise HTTPException(400, "INVALID_MERCHANT")
    if body.category not in CATEGORIES:
        raise HTTPException(400, "INVALID_CATEGORY")
    if body.date > date.today():
        raise HTTPException(400, "FUTURE_DATE")  # 미래 날짜는 기록할 수 없다 (시안과 동일)
    # 기록할 카드: 사용 중인 카드 중 신용카드를 우선한다
    card = db.scalar(
        select(m.Card).where(m.Card.member_id == member.id, m.Card.status == "active")
        .order_by(case((m.Card.type == "credit", 0), else_=1), m.Card.issued_at)
    )
    if not card:
        raise HTTPException(409, "NO_ACTIVE_CARD")
    tx = m.CardTransaction(
        card_id=card.id, kind="approval", merchant=merchant, amount=body.amount, installment_months=0,
        occurred_at=datetime.combine(body.date, time(12, 0)))
    db.add(tx)
    db.flush()
    db.add(m.LedgerTxCategory(card_transaction_id=tx.id, member_id=member.id, category=body.category, source="user"))
    _adjust_card_bill(db, member.id, card, body.date, body.amount)
    db.commit()
    return {"id": tx.id}


@router.delete("/transactions/{tx_id}", status_code=204)
def delete_transaction(tx_id: str, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    row = db.execute(
        select(m.CardTransaction, m.LedgerTxCategory)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .join(m.LedgerTxCategory, m.LedgerTxCategory.card_transaction_id == m.CardTransaction.id)
        .where(m.CardTransaction.id == tx_id, m.Card.member_id == member.id)
    ).first()
    if not row:
        raise HTTPException(404, "NOT_FOUND")
    tx, cat = row
    if cat.source != "user" or tx.kind != "approval":
        raise HTTPException(409, "NOT_DELETABLE")
    if db.scalar(select(m.CardTransaction.id).where(m.CardTransaction.original_id == tx.id)):
        raise HTTPException(409, "HAS_CANCEL")
    card = db.get(m.Card, tx.card_id)
    _adjust_card_bill(db, member.id, card, tx.occurred_at.date(), -tx.amount)
    db.delete(cat)
    db.flush()
    db.delete(tx)
    db.commit()


# ───────────── 예산 · 예정 출금 설정 ─────────────


class BudgetIn(BaseModel):
    total: int = Field(gt=0, le=10_000_000_000)
    categories: dict[str, int] = {}  # 예: {"배달": 90000}


@router.put("/budget")
def put_budget(body: BudgetIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """이번 달 월 예산과 카테고리 예산을 저장한다(없으면 만든다)."""
    for name, amount in body.categories.items():
        if name not in CATEGORIES:
            raise HTTPException(400, "INVALID_CATEGORY")
        if amount <= 0:
            raise HTTPException(400, "INVALID_AMOUNT")
    month = this_month()
    budget = db.scalar(select(m.Budget).where(m.Budget.member_id == member.id, m.Budget.month == month))
    if budget:
        budget.total_amount = body.total
    else:
        budget = m.Budget(member_id=member.id, month=month, total_amount=body.total, emergency_floor=0)
        db.add(budget)
        db.flush()
    for name, amount in body.categories.items():
        row = db.get(m.CategoryBudget, (budget.id, name))
        if row:
            row.amount = amount
        else:
            db.add(m.CategoryBudget(budget_id=budget.id, category=name, amount=amount))
    db.commit()
    return build_summary(db, member.id, month)


class PlannedIn(BaseModel):
    amount: int = Field(ge=0, le=10_000_000_000)


@router.put("/planned-outflows/{po_id}")
def put_planned(po_id: str, body: PlannedIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """예정 출금(카드대금 등) 금액을 고친다. 계좌 잔액은 계좌 도메인 소유라 여기서 바꾸지 않는다."""
    row = db.get(m.PlannedOutflow, po_id)
    if not row or row.member_id != member.id:
        raise HTTPException(404, "NOT_FOUND")
    row.amount = body.amount
    db.commit()
    return build_summary(db, member.id, this_month())
