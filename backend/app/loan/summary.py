"""[역할] 메인 화면(/api/home)이 읽는 대출 요약: 내 대출 합계·다음 상환일, 상품 카드 목록. 대출 테이블은 읽기만 한다."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from . import catalog as C
from .application import products
from .database import Database

TYPE_KEY = {"GENERAL": "general", "POLICY": "gov", "INST": "org", "REFI": "refi"}
LIVE = ("ACTIVE", "OVERDUE", "ACCELERATED")


def _months(n: int) -> str:
    return f"{n // 12}년" if n % 12 == 0 else f"{n}개월"


def _icon(p: dict) -> str:
    if p["business_type"] == "REFI":
        return "swap"
    if p["business_type"] == "INST" and p["inst_kind"] == "A":
        return "shield"
    return {"JEONSE": "home", "MORTGAGE": "key"}.get(p["collateral_type"], "card")


def home_summary(session: Session, user_id: int) -> dict:
    db = Database(session)
    today = date.today().isoformat()
    items, total, next_due, due_total = [], 0, None, 0
    for a in db.all("""SELECT a.contract_no, a.balance, a.principal, a.rate, p.name FROM loan_account a
                       JOIN product_catalog p ON p.product_id = a.product_id
                       WHERE a.user_id = ? AND a.status = ANY(?) ORDER BY a.start_date DESC, a.contract_no""", (user_id, list(LIVE))):
        up = db.one("SELECT due_date, principal + interest AS amount FROM repayment_schedule WHERE contract_no = ? AND due_date > ? ORDER BY seq LIMIT 1",
                    (a["contract_no"], today))
        total += a["balance"]
        items.append({"contractNo": a["contract_no"], "productName": a["name"], "balance": a["balance"], "amount": a["principal"],
                      "rate": float(Decimal(str(a["rate"]))), "nextDueDate": up["due_date"] if up else None,
                      "nextDueAmount": up["amount"] if up else 0})
        if up and (next_due is None or up["due_date"] < next_due):
            next_due = up["due_date"]
    for it in items:
        if next_due and it["nextDueDate"] == next_due:
            due_total += it["nextDueAmount"]
    prods = []
    for p in products(db):
        t = p["term_options"]
        prods.append({"id": p["product_id"], "type": TYPE_KEY[p["business_type"]], "name": p["name"], "maxAmount": p["max_amount"],
                      "term": _months(t[0]) if len(t) == 1 else f"{_months(min(t))} ~ {_months(max(t))}",
                      "tags": [C.TYPE_NM[p["business_type"]], C.CAT_NM[p["collateral_type"]]], "icon": _icon(p)})
    return {"count": len(items), "totalBalance": total, "nextDueDate": next_due, "nextDueAmount": due_total, "items": items, "products": prods}
