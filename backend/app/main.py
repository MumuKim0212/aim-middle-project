from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .db import SessionLocal, engine, get_db
from .deps import current_member
from .ledger import router as ledger_router
from .seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    m.Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="AIM Bank API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(ledger_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _loan_summary(db: Session, member_id: str) -> dict:
    today = date.today()
    rows = db.execute(
        select(m.Contract, m.LoanTerms, m.Pricing, m.LoanApplication)
        .join(m.LoanApplication, m.LoanApplication.id == m.Contract.application_id)
        .join(m.LoanTerms, m.LoanTerms.application_id == m.Contract.application_id)
        .join(m.Pricing, m.Pricing.application_id == m.Contract.application_id)
        .where(m.LoanApplication.member_id == member_id)
    ).all()
    items, total, due_total, next_due = [], 0, 0, None
    for contract, terms, pricing, _app in rows:
        sched = db.scalars(
            select(m.RepaymentSchedule).where(m.RepaymentSchedule.contract_no == contract.contract_no)
            .order_by(m.RepaymentSchedule.seq)
        ).all()
        paid = [s for s in sched if s.due_date <= today]
        upcoming = next((s for s in sched if s.due_date > today), None)
        balance = paid[-1].balance if paid else terms.amount
        total += balance
        if upcoming:
            if next_due is None or upcoming.due_date < next_due:
                next_due = upcoming.due_date
        items.append({
            "contractNo": contract.contract_no,
            "productName": db.get(m.ProductCatalog, terms.product_id).name,
            "balance": balance,
            "amount": terms.amount,
            "rate": float(pricing.final_rate) * 100,
            "nextDueDate": upcoming.due_date.isoformat() if upcoming else None,
            "nextDueAmount": (upcoming.principal + upcoming.interest) if upcoming else 0,
        })
    for it in items:
        if next_due and it["nextDueDate"] == next_due.isoformat():
            due_total += it["nextDueAmount"]
    return {
        "count": len(items),
        "totalBalance": total,
        "nextDueDate": next_due.isoformat() if next_due else None,
        "nextDueAmount": due_total,
        "items": items,
    }


@app.get("/api/home")
def home(member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """메인 화면 한 번에 필요한 요약 (계좌·카드·가계부·대출)."""
    today = date.today()
    month = today.strftime("%Y-%m")
    month_start = today.replace(day=1)

    accounts = db.scalars(
        select(m.Account).where(m.Account.member_id == member.id, m.Account.status == "active")
        .order_by(m.Account.is_primary.desc(), m.Account.id)
    ).all()

    cards = db.scalars(
        select(m.Card).where(m.Card.member_id == member.id, m.Card.status != "terminated")
        .order_by(m.Card.issued_at)
    ).all()
    card_ids = [c.id for c in cards]
    approved = cancelled = 0
    if card_ids:
        sums = dict(db.execute(
            select(m.CardTransaction.kind, func.coalesce(func.sum(m.CardTransaction.amount), 0))
            .where(m.CardTransaction.card_id.in_(card_ids), m.CardTransaction.occurred_at >= month_start)
            .group_by(m.CardTransaction.kind)
        ).all())
        approved, cancelled = sums.get("approval", 0), sums.get("cancel", 0)
    spent = approved - cancelled

    budget = db.scalar(select(m.Budget).where(m.Budget.member_id == member.id, m.Budget.month == month))
    budget_total = budget.total_amount if budget else 0

    products = db.scalars(select(m.ProductCatalog).order_by(m.ProductCatalog.product_id)).all()

    return {
        "member": {"id": member.id, "name": member.name},
        "accounts": {
            "totalBalance": sum(a.balance for a in accounts),
            "items": [
                {"id": a.id, "bankName": a.bank_name, "masked": a.account_masked,
                 "balance": a.balance, "primary": a.is_primary}
                for a in accounts
            ],
        },
        "cards": {
            "count": len(cards),
            "monthSpent": spent,
            "items": [
                {"id": c.id, "name": c.name, "type": c.type, "last4": c.number_last4, "status": c.status}
                for c in cards
            ],
        },
        "ledger": {
            "month": month,
            "budget": budget_total,
            "spent": spent,
            "remaining": budget_total - spent,
            "usageRate": round(spent / budget_total * 100, 1) if budget_total else 0,
        },
        "loans": {
            **_loan_summary(db, member.id),
            "products": [
                {"id": p.product_id, "type": p.type, "name": p.name,
                 "maxAmount": (p.rules or {}).get("max_amount"),
                 "term": (p.rules or {}).get("term"),
                 "tags": (p.rules or {}).get("tags", []),
                 "icon": (p.rules or {}).get("icon")}
                for p in products
            ],
        },
    }
