"""카드 API (/api). 기획서: docs/card, 개발 명세: docs/dev/card/backend-spec.md.

오류 응답은 {code, message, details} 형태, 쓰기 순서는 인증 → 입력 검증 → 404 → 409/422 → 본인 재확인(간편비밀번호) → 실행.
"""
import base64
import hashlib
import hmac
import json
import os
import random
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .card_cycles import (
    KST, add_months, billed, cycle_lines, cycle_totals, date_of, first_due_date, is_simple_pin,
    kst_date, next_payment_date, usage_rate, used_amount,
)
from .accounts.service import BANK_NAME, CHECKING, mask
from .auth.deps import current_user, require_pin_verified
from .db import get_db

router = APIRouter(prefix="/api")

MAX_CARDS = 3
PIN_RE = re.compile(r"^[0-9]{4}$")
CURSOR_SECRET = os.getenv("CARD_CURSOR_SECRET", "dev-only-cursor-secret").encode()

ACTIONS = {
    "active": ["view_transactions", "view_limit", "suspend", "report_lost", "terminate"],
    "suspended": ["view_transactions", "view_limit", "resume", "report_lost", "terminate"],
    "lost": ["view_transactions", "view_limit", "terminate"],
    "terminated": ["view_transactions"],
}
STATUS_ORDER = {"active": 0, "suspended": 1, "lost": 2, "terminated": 3}
INCOME_LIMIT = {"none": None, "lt_10m": None, "10m_20m": 1_000_000, "20m_40m": 3_000_000,
                "40m_70m": 5_000_000, "gte_70m": 10_000_000}
TERMINATE_REASONS = {"unused", "benefit_complaint", "other_card", "lost_cleanup", "other"}
UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


# ───────────────────────── 오류·공통 ─────────────────────────


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None,
                 headers: dict | None = None):
        self.status, self.code, self.message, self.details, self.headers = status, code, message, details, headers


def api_error_response(_: Request, e: ApiError) -> JSONResponse:
    body = {"code": e.code, "message": e.message}
    if e.details is not None:
        body["details"] = e.details
    return JSONResponse(body, status_code=e.status, headers=e.headers)


def internal_error_response(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse({"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다."}, status_code=500)


def validation(fields: list[tuple[str, str]]) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", "입력값을 확인해 주세요.",
                    {"fields": [{"field": f, "reason": r} for f, r in fields]})


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_kst() -> date:
    return datetime.now(KST).date()


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(KST).isoformat(timespec="seconds") if dt else None


async def json_body(request: Request) -> dict:
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "JSON 요청만 받을 수 있습니다.")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise validation([("$", "INVALID_FORMAT")])
    return body


def clean(v) -> str | None:
    """앞뒤 공백 제거 + NFC. 문자열이 아니면 None."""
    return unicodedata.normalize("NFC", v).strip() if isinstance(v, str) else None


# ───────────────────────── 조회 헬퍼 ─────────────────────────


def owned_card(db: Session, user_id: int, card_id: str) -> m.Card:
    card = db.get(m.Card, card_id)
    if not card or card.user_id != user_id:
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
    return card


def card_txs(db: Session, card_id: str) -> list[m.CardTransaction]:
    # shortcut: 카드의 거래를 전부 읽어 메모리에서 계산한다, 카드당 거래가 수만 건이 되면 13개월 범위로 줄인다
    return list(db.scalars(select(m.CardTransaction).where(m.CardTransaction.card_id == card_id)))


def totals_of(db: Session, card: m.Card) -> dict[date, int]:
    return cycle_totals(cycle_lines(card_txs(db, card.id), card.payment_day))


def credit_view(db: Session, card: m.Card) -> dict:
    used = used_amount(totals_of(db, card), today_kst())
    return {"total": card.credit_limit, "used": used, "remaining": max(0, card.credit_limit - used),
            "usageRate": usage_rate(used, card.credit_limit)}


def debit_view(card: m.Card) -> dict:
    return {"perTx": card.debit_per_tx, "perDay": card.debit_per_day}


def payment_account(card: m.Card) -> dict:
    return {"accountId": card.payment_account_id, "bankName": card.payment_bank_name,
            "accountMasked": card.payment_account_masked}


def masked_number(card: m.Card) -> str:
    return f"****-****-****-{card.number_last4}"


def active_count(db: Session, user_id: int, type_: str) -> int:
    return db.scalar(select(func.count()).select_from(m.Card).where(
        m.Card.user_id == user_id, m.Card.type == type_, m.Card.status.in_(("active", "suspended")))) or 0


def state_invalid(card: m.Card, allowed: list[str]) -> ApiError:
    return ApiError(409, "CARD_STATE_INVALID", "현재 카드 상태에서는 처리할 수 없습니다.",
                    {"currentStatus": card.status, "allowedStatuses": allowed})


def card_detail(db: Session, c: m.Card) -> dict:
    return {
        "id": c.id, "name": c.name, "type": c.type, "numberMasked": masked_number(c), "expiry": c.expiry,
        "status": c.status, "issuedAt": c.issued_at.isoformat(), "paymentAccount": payment_account(c),
        "paymentDay": c.payment_day, "limit": credit_view(db, c) if c.type == "credit" else None,
        "debitLimit": debit_view(c) if c.type == "debit" else None,
        "suspendedAt": iso(c.suspended_at), "lostAt": iso(c.lost_at), "lostReason": c.lost_reason,
        "terminatedAt": iso(c.terminated_at), "availableActions": ACTIONS[c.status],
    }


# ───────────────────────── 01 목록·상세 ─────────────────────────


@router.get("/cards")
def list_cards(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    raw = request.query_params.get("includeTerminated", "false")
    if raw not in ("true", "false"):
        raise validation([("includeTerminated", "INVALID_FORMAT")])
    cards = list(db.scalars(select(m.Card).where(m.Card.user_id == user.id)))
    live = sorted((c for c in cards if c.status != "terminated"),
                  key=lambda c: (STATUS_ORDER[c.status], -c.issued_at.toordinal(), c.id))
    gone = sorted((c for c in cards if c.status == "terminated"), key=lambda c: c.terminated_at, reverse=True)
    return {
        "items": [{"id": c.id, "name": c.name, "type": c.type, "numberMasked": masked_number(c),
                   "status": c.status, "issuedAt": c.issued_at.isoformat(), "terminatedAt": iso(c.terminated_at)}
                  for c in live + (gone if raw == "true" else [])],
        "terminatedCount": len(gone),
    }


@router.get("/cards/{card_id}")
def get_card(card_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return card_detail(db, owned_card(db, user.id, card_id))


# ───────────────────────── 02 이용내역 ─────────────────────────


def _sign_cursor(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(hmac.new(CURSOR_SECRET, raw, hashlib.sha256).digest()).rstrip(b"=")
    return f"{raw.decode()}.{sig.decode()}"


def _open_cursor(cursor: str, user_id: int, fingerprint: str) -> dict:
    bad = ApiError(400, "INVALID_CURSOR", "커서가 올바르지 않습니다.")
    try:
        raw, sig = cursor.split(".")
        want = base64.urlsafe_b64encode(hmac.new(CURSOR_SECRET, raw.encode(), hashlib.sha256).digest()).rstrip(b"=")
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        ok = (hmac.compare_digest(sig.encode(), want) and payload["m"] == user_id
              and payload["f"] == fingerprint and payload["e"] > time.time() * 1000)
    except (ValueError, KeyError, TypeError):
        raise bad
    if not ok:
        raise bad
    return payload


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
    except ValueError:
        return None


def _tx_item(t: m.CardTransaction, c: m.Card) -> dict:
    return {"id": t.id, "cardId": c.id, "cardName": c.name, "cardType": c.type, "cardNumberLast4": c.number_last4,
            "occurredAt": iso(t.occurred_at), "merchant": t.merchant, "amount": t.amount, "kind": t.kind,
            "originalId": t.original_id, "installmentMonths": t.installment_months}


@router.get("/card-transactions")
def list_transactions(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    qp = request.query_params
    fields: list[tuple[str, str]] = []
    parsed: dict[str, date | None] = {}
    for key in ("from", "to"):
        parsed[key] = _parse_date(qp.get(key))
        if not qp.get(key):
            fields.append((key, "REQUIRED"))
        elif parsed[key] is None:
            fields.append((key, "INVALID_FORMAT"))
    d_from, d_to = parsed["from"], parsed["to"]
    if d_from and d_to:
        if d_from > d_to:
            fields.append(("from", "FROM_AFTER_TO"))
        if d_to > today_kst():
            fields.append(("to", "TO_IN_FUTURE"))
        if d_from < add_months(d_to, -12):
            fields.append(("from", "PERIOD_TOO_LONG"))
    kind = qp.get("kind", "all")
    if kind not in ("all", "approval", "cancel"):
        fields.append(("kind", "INVALID_ENUM"))
    merchant = (clean(qp.get("merchant")) or "").lower()
    if len(merchant) > 50:
        fields.append(("merchant", "TOO_LONG"))
    try:
        limit = int(qp.get("limit", "20"))
        if not 1 <= limit <= 50:
            raise ValueError
    except ValueError:
        limit = 20
        fields.append(("limit", "OUT_OF_RANGE"))
    if fields:
        raise validation(fields)

    cards = {c.id: c for c in db.scalars(select(m.Card).where(m.Card.user_id == user.id))}
    card_id = qp.get("cardId")
    if card_id and card_id not in cards:
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")

    fingerprint = hashlib.sha256(json.dumps([card_id or "", str(d_from), str(d_to), kind, merchant]).encode()).hexdigest()
    conds = [
        m.CardTransaction.card_id.in_([card_id] if card_id else list(cards)),
        m.CardTransaction.occurred_at >= datetime(d_from.year, d_from.month, d_from.day, tzinfo=KST),
        m.CardTransaction.occurred_at < datetime(d_to.year, d_to.month, d_to.day, tzinfo=KST) + timedelta(days=1),
    ]
    if kind != "all":
        conds.append(m.CardTransaction.kind == kind)
    if merchant:
        escaped = merchant.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(func.lower(m.CardTransaction.merchant).like(f"%{escaped}%", escape="\\"))

    approval_total, cancel_total, count = db.execute(select(
        func.coalesce(func.sum(case((m.CardTransaction.kind == "approval", m.CardTransaction.amount), else_=0)), 0),
        func.coalesce(func.sum(case((m.CardTransaction.kind == "cancel", m.CardTransaction.amount), else_=0)), 0),
        func.count(),
    ).where(*conds)).one()

    page = list(conds)
    if qp.get("cursor"):
        cur = _open_cursor(qp["cursor"], user.id, fingerprint)
        page.append(tuple_(m.CardTransaction.occurred_at, m.CardTransaction.id)
                    < tuple_(datetime.fromtimestamp(cur["t"] / 1000, timezone.utc), cur["id"]))
    rows = list(db.scalars(select(m.CardTransaction).where(*page)
                           .order_by(m.CardTransaction.occurred_at.desc(), m.CardTransaction.id.desc())
                           .limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = _sign_cursor({"t": int(last.occurred_at.timestamp() * 1000), "id": last.id, "f": fingerprint,
                                    "m": user.id, "e": int((time.time() + 86400) * 1000)})
    return {
        "summary": {"approvalTotal": approval_total, "cancelTotal": cancel_total,
                    "netTotal": approval_total - cancel_total, "count": count},
        "items": [_tx_item(t, cards[t.card_id]) for t in rows],
        "nextCursor": next_cursor,
    }


@router.get("/card-transactions/{tx_id}")
def get_transaction(tx_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(m.CardTransaction, tx_id)
    card = db.get(m.Card, t.card_id) if t else None
    if not t or card.user_id != user.id:
        raise ApiError(404, "TRANSACTION_NOT_FOUND", "거래를 찾을 수 없습니다.")
    o = db.get(m.CardTransaction, t.original_id) if t.original_id else None
    return {**_tx_item(t, card),
            "original": {"id": o.id, "occurredAt": iso(o.occurred_at), "merchant": o.merchant, "amount": o.amount}
            if o else None}


# ───────────────────────── 03 청구 ─────────────────────────


@router.get("/card-billing/upcoming")
def upcoming_billing(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    today = today_kst()
    credit = list(db.scalars(select(m.Card).where(
        m.Card.user_id == user.id, m.Card.type == "credit", m.Card.status != "terminated")))
    groups: dict[tuple[date, str], dict] = {}
    for c in credit:
        lines = cycle_lines(card_txs(db, c.id), c.payment_day)
        p = next_payment_date(today, c.payment_day)
        amount = billed(cycle_totals(lines), p)
        if amount == 0:
            continue
        items = [{"kind": ln.kind, "occurredAt": iso(ln.tx.occurred_at), "merchant": ln.tx.merchant,
                  "amount": ln.amount,
                  "installment": {"round": ln.installment[0], "months": ln.installment[1]} if ln.installment else None}
                 for ln in sorted((x for x in lines if x.cycle == p), key=lambda x: x.tx.occurred_at, reverse=True)]
        group = groups.setdefault((p, c.payment_account_id), {
            "paymentDate": p.isoformat(), "isCurrentMonth": (p.year, p.month) == (today.year, today.month),
            "paymentAccount": payment_account(c), "amount": 0, "balance": None, "balanceStatus": "ok",
            "shortfall": None, "cards": []})
        group["amount"] += amount
        group["cards"].append({
            "cardId": c.id, "cardName": c.name, "status": c.status, "cardNumberLast4": c.number_last4,
            "amount": amount,
            "usagePeriod": {"from": date_of(p.year, p.month - 1, 1).isoformat(),
                            "to": (p.replace(day=1) - timedelta(days=1)).isoformat()},
            "items": items})
    payments = [g for _, g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1]))]
    for g in payments:
        account = db.get(m.Account, g["paymentAccount"]["accountId"])
        if account is None:
            g["balanceStatus"] = "unavailable"
            continue
        g["balance"] = account.balance
        g["balanceStatus"] = "ok" if account.balance >= g["amount"] else "insufficient"
        g["shortfall"] = max(0, g["amount"] - account.balance)
    nxt = payments[0]["paymentDate"] if payments else None
    return {
        "asOf": today.isoformat(), "hasCreditCard": bool(credit),
        "thisMonthTotal": sum(g["amount"] for g in payments if g["isCurrentMonth"]),
        "nextPaymentDate": nxt,
        "daysUntilPayment": (date.fromisoformat(nxt) - today).days if nxt else None,
        "payments": payments,
    }


# ───────────────────────── 04 분실·정지·재개 / 07 해지 공통 ─────────────────────────


def _status_result(c: m.Card) -> dict:
    return {"id": c.id, "status": c.status, "suspendedAt": iso(c.suspended_at), "lostAt": iso(c.lost_at),
            "lostReason": c.lost_reason}


def _change_status(request: Request, db: Session, user_id: int, card_id: str, body: dict, *, action: str, allowed: list[str],
                   to: str, values: dict, extra_fields: list[tuple[str, str]] = ()) -> dict:
    fields = [*extra_fields]
    if fields:
        raise validation(fields)
    card = owned_card(db, user_id, card_id)
    if card.status not in allowed:
        raise state_invalid(card, allowed)
    require_pin_verified(request)
    result = db.execute(update(m.Card).where(
        m.Card.id == card_id, m.Card.user_id == user_id, m.Card.status.in_(allowed)).values(status=to, **values))
    if result.rowcount == 0:  # 본인 재확인 사이에 다른 요청이 먼저 상태를 바꿨다
        db.rollback()
        raise state_invalid(owned_card(db, user_id, card_id), allowed)
    db.add(m.CardStatusHistory(card_id=card_id, user_id=user_id, action=action, from_status=card.status,
                               to_status=to, request_id=m.new_id("req")))
    db.commit()
    db.refresh(card)
    return _status_result(card)


@router.post("/cards/{card_id}/suspend")
def suspend_card(request: Request, card_id: str, body: dict = Depends(json_body), user: m.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    return _change_status(request, db, user.id, card_id, body, action="suspend", allowed=["active"], to="suspended",
                          values={"suspended_at": now_utc()})


@router.post("/cards/{card_id}/resume")
def resume_card(request: Request, card_id: str, body: dict = Depends(json_body), user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    return _change_status(request, db, user.id, card_id, body, action="resume", allowed=["suspended"], to="active",
                          values={"suspended_at": None})


@router.post("/cards/{card_id}/report-lost")
def report_lost(request: Request, card_id: str, body: dict = Depends(json_body), user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    reason = body.get("reason")
    extra = ([("reason", "REQUIRED")] if reason is None
             else [("reason", "INVALID_ENUM")] if reason not in ("lost", "stolen") else [])
    return _change_status(request, db, user.id, card_id, body, action="report_lost", allowed=["active", "suspended"],
                          to="lost", extra_fields=extra,
                          values={"suspended_at": None, "lost_at": now_utc(), "lost_reason": reason})


# ───────────────────────── 05 한도 ─────────────────────────


@router.get("/cards/{card_id}/limit")
def get_card_limit(card_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    c = owned_card(db, user.id, card_id)
    if c.status == "terminated":
        raise state_invalid(c, ["active", "suspended", "lost"])
    return {"cardId": c.id, "type": c.type, "status": c.status,
            "credit": credit_view(db, c) if c.type == "credit" else None,
            "debit": debit_view(c) if c.type == "debit" else None}


# ───────────────────────── 06 신규 발급·신청 ─────────────────────────


@router.get("/card-products")
def list_card_products(db: Session = Depends(get_db)):
    products = db.scalars(select(m.CardProduct).where(m.CardProduct.active).order_by(m.CardProduct.id))
    return {"items": [{"id": p.id, "type": p.type, "name": p.name, "description": p.description} for p in products]}


def _age_under_19(user: m.User) -> bool:
    b, t = user.birth_date, today_kst()  # 생년월일이 없으면 통과
    return bool(b) and t.year - b.year - ((t.month, t.day) < (b.month, b.day)) < 19


@router.get("/card-applications/eligibility")
def apply_eligibility(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    def one(type_: str) -> dict:
        current = active_count(db, user.id, type_)
        reason = ("AGE_UNDER_19" if type_ == "credit" and _age_under_19(user)
                  else "COUNT_EXCEEDED" if current >= MAX_CARDS else None)
        return {"available": reason is None, "reason": reason, "currentCount": current, "maxCount": MAX_CARDS}
    return {"types": {"credit": one("credit"), "debit": one("debit")}}


def _validate_apply(b: dict, key: str | None, db: Session) -> tuple[dict, list[tuple[str, str]]]:
    """(정규화된 요청, 필드 오류). 알 수 없는 필드는 무시한다."""
    f: list[tuple[str, str]] = []
    if key and not UUID4_RE.match(key):
        f.append(("Idempotency-Key", "INVALID_FORMAT"))
    type_ = b.get("type")
    if type_ is None:
        f.append(("type", "REQUIRED"))
    elif type_ not in ("credit", "debit"):
        f.append(("type", "INVALID_ENUM"))
    product_id = b.get("productId")
    if not product_id:
        f.append(("productId", "REQUIRED"))
    else:
        product = db.get(m.CardProduct, product_id) if isinstance(product_id, str) else None
        if not product or not product.active:
            f.append(("productId", "INVALID_ENUM"))
        elif product.type != type_:
            f.append(("productId", "PRODUCT_TYPE_MISMATCH"))
    if not b.get("paymentAccountId"):
        f.append(("paymentAccountId", "REQUIRED"))
    elif not isinstance(b["paymentAccountId"], int) or isinstance(b["paymentAccountId"], bool)             or not 0 < b["paymentAccountId"] < 2**63:
        f.append(("paymentAccountId", "INVALID_FORMAT"))
    agreements = b.get("agreements") if isinstance(b.get("agreements"), dict) else {}
    pay_day, income = b.get("paymentDay"), b.get("incomeRange")
    if type_ == "credit":
        if pay_day is not None:
            if isinstance(pay_day, bool) or not isinstance(pay_day, int):
                f.append(("paymentDay", "INVALID_FORMAT"))
            elif not 1 <= pay_day <= 28:
                f.append(("paymentDay", "OUT_OF_RANGE"))
        if not income:
            f.append(("incomeRange", "REQUIRED"))
        elif income not in INCOME_LIMIT:
            f.append(("incomeRange", "INVALID_ENUM"))
        if "creditInquiry" not in agreements:
            f.append(("agreements.creditInquiry", "REQUIRED"))
        elif agreements["creditInquiry"] is not True:
            f.append(("agreements.creditInquiry", "MUST_BE_TRUE"))
    elif type_ == "debit":
        if pay_day is not None:
            f.append(("paymentDay", "NOT_ALLOWED"))
        if income is not None:
            f.append(("incomeRange", "NOT_ALLOWED"))
        if "creditInquiry" in agreements:
            f.append(("agreements.creditInquiry", "NOT_ALLOWED"))
    card_pin = b.get("cardPin")
    if not card_pin:
        f.append(("cardPin", "REQUIRED"))
    elif not (isinstance(card_pin, str) and PIN_RE.match(card_pin)):
        f.append(("cardPin", "INVALID_FORMAT"))
    elif is_simple_pin(card_pin):
        f.append(("cardPin", "PIN_TOO_SIMPLE"))
    recipient = clean(b.get("recipient"))
    if not recipient:
        f.append(("recipient", "REQUIRED" if b.get("recipient") in (None, "") or recipient == "" else "INVALID_FORMAT"))
    elif len(recipient) > 20:
        f.append(("recipient", "TOO_LONG"))
    phone = b.get("phone")
    if not phone:
        f.append(("phone", "REQUIRED"))
    elif not (isinstance(phone, str) and re.fullmatch(r"010-[0-9]{4}-[0-9]{4}", phone)):
        f.append(("phone", "INVALID_FORMAT"))
    address = b.get("address") if isinstance(b.get("address"), dict) else {}
    line1, line2 = clean(address.get("line1")), clean(address.get("line2")) or ""
    if not line1:
        f.append(("address.line1", "REQUIRED"))
    elif len(line1) > 100:
        f.append(("address.line1", "TOO_LONG"))
    if len(line2) > 100:
        f.append(("address.line2", "TOO_LONG"))
    for k in ("cardTerms", "privacy"):
        if k not in agreements:
            f.append((f"agreements.{k}", "REQUIRED"))
        elif agreements[k] is not True:
            f.append((f"agreements.{k}", "MUST_BE_TRUE"))
    req = {"type": type_, "productId": product_id, "paymentAccountId": b.get("paymentAccountId"),
           "paymentDay": (pay_day if pay_day is not None else 25) if type_ == "credit" else None,
           "incomeRange": income if type_ == "credit" else None, "recipient": recipient, "phone": phone,
           "line1": line1, "line2": line2 or None, "cardTerms": agreements.get("cardTerms"),
           "privacy": agreements.get("privacy"),
           "creditInquiry": agreements.get("creditInquiry") if type_ == "credit" else None}
    return req, f


def _fingerprint(req: dict) -> str:
    # 카드 비밀번호(cardPin)는 req 에 없다. 서버 기본값(결제일 25)이 이미 적용돼 있다.
    return hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _replay(row: m.IdempotencyKey, fingerprint: str) -> JSONResponse:
    if row.fingerprint != fingerprint:
        raise ApiError(422, "IDEMPOTENCY_KEY_REUSED", "같은 키로 다른 내용을 보낼 수 없습니다.")
    return JSONResponse(json.loads(row.response_body), status_code=201)


def _find_key(db: Session, user_id: int, key: str) -> m.IdempotencyKey | None:
    return db.scalar(select(m.IdempotencyKey).where(
        m.IdempotencyKey.user_id == user_id, m.IdempotencyKey.idem_key == key,
        m.IdempotencyKey.expires_at > now_utc(), m.IdempotencyKey.response_body.is_not(None)))


def _issue_card(db: Session, user_id: int, req: dict, account: m.Account, granted: int | None) -> m.Card:
    today = today_kst()
    product = db.get(m.CardProduct, req["productId"])
    credit = req["type"] == "credit"
    for _ in range(10):  # 끝 4자리가 이 회원의 모든 카드(해지 포함)와 겹치면 다시 뽑는다
        card = m.Card(
            user_id=user_id, product_id=product.id, name=product.name, type=req["type"],
            number_last4=f"{random.randrange(10000):04d}",
            expiry=f"{today.month:02d}/{(today.year + 5) % 100:02d}", issued_at=today,
            payment_account_id=account.id, payment_bank_name=BANK_NAME,
            payment_account_masked=mask(account.account_no),
            payment_day=req["paymentDay"] if credit else None, credit_limit=granted if credit else None,
            debit_per_tx=None if credit else 1_000_000, debit_per_day=None if credit else 3_000_000)
        try:
            with db.begin_nested():
                db.add(card)
                db.flush()
            return card
        except IntegrityError:
            continue
    raise ApiError(500, "INTERNAL_ERROR", "카드 번호를 만들지 못했습니다.")


@router.post("/card-applications", status_code=201)
def apply_card(request: Request, body: dict = Depends(json_body), user: m.User = Depends(current_user),
               db: Session = Depends(get_db)):
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key 헤더가 필요합니다.")
    req, fields = _validate_apply(body, key, db)
    if fields:
        raise validation(fields)
    fingerprint = _fingerprint(req)
    saved = _find_key(db, user.id, key)
    if saved:
        return _replay(saved, fingerprint)

    account = db.scalar(select(m.Account).where(
        m.Account.id == req["paymentAccountId"], m.Account.user_id == user.id, m.Account.status == "active",
        m.Account.product_id == CHECKING))  # 결제 계좌는 저축예금만(공통.md 8장). 계좌 후보 조회는 계좌 파트 API
    if not account:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "계좌를 찾을 수 없습니다.")
    if req["type"] == "credit" and _age_under_19(user):
        raise ApiError(422, "APPLICANT_NOT_ELIGIBLE", "만 19세 이상부터 신청할 수 있습니다.", {"reason": "AGE_UNDER_19"})
    count_error = lambda n: ApiError(409, "CARD_COUNT_LIMIT_EXCEEDED", "보유 한도를 초과했습니다.",  # noqa: E731
                                     {"type": req["type"], "current": n, "max": MAX_CARDS})
    if (n := active_count(db, user.id, req["type"])) >= MAX_CARDS:
        raise count_error(n)
    require_pin_verified(request)

    db.rollback()  # 위의 읽기 트랜잭션을 끝내고 짧은 쓰기 트랜잭션을 연다
    now = now_utc()
    db.execute(m.IdempotencyKey.__table__.delete().where(
        m.IdempotencyKey.user_id == user.id, m.IdempotencyKey.idem_key == key, m.IdempotencyKey.expires_at <= now))
    inserted = db.execute(pg_insert(m.IdempotencyKey).values(
        user_id=user.id, idem_key=key, fingerprint=fingerprint, created_at=now,
        expires_at=now + timedelta(hours=24)).on_conflict_do_nothing().returning(m.IdempotencyKey.idem_key))
    if inserted.first() is None:  # 같은 키의 다른 요청이 끝나길 기다렸다가 저장된 응답을 돌려준다
        db.rollback()
        saved = _find_key(db, user.id, key)
        if saved:
            return _replay(saved, fingerprint)
        raise ApiError(409, "CARD_STATE_INVALID", "같은 신청이 처리 중입니다. 잠시 후 다시 시도해 주세요.")
    db.execute(pg_insert(m.CardIssueQuota).values(user_id=user.id, type=req["type"]).on_conflict_do_nothing())
    db.execute(select(m.CardIssueQuota).where(
        m.CardIssueQuota.user_id == user.id, m.CardIssueQuota.type == req["type"]).with_for_update())
    if (n := active_count(db, user.id, req["type"])) >= MAX_CARDS:
        db.rollback()
        raise count_error(n)

    granted = INCOME_LIMIT[req["incomeRange"]] if req["type"] == "credit" else None
    approved = req["type"] == "debit" or granted is not None
    card = _issue_card(db, user.id, req, account, granted) if approved else None
    application = m.CardApplication(
        user_id=user.id, type=req["type"], product_id=req["productId"], payment_account_id=account.id,
        payment_day=req["paymentDay"], income_range=req["incomeRange"], recipient=req["recipient"],
        phone=req["phone"], address_line1=req["line1"], address_line2=req["line2"],
        agree_card_terms=True, agree_privacy=True, agree_credit_inquiry=req["creditInquiry"],
        status="approved" if approved else "rejected", reject_reason=None if approved else "INCOME_INSUFFICIENT",
        granted_limit=granted, result_card_id=card.id if card else None, requested_at=now)
    db.add(application)
    if card:
        db.add(m.CardStatusHistory(card_id=card.id, user_id=user.id, action="issue", from_status=None,
                                   to_status="active", request_id=m.new_id("req")))
    db.flush()
    response = {
        "id": application.id, "type": req["type"], "status": application.status, "requestedAt": iso(now),
        "grantedLimit": granted, "rejectReason": application.reject_reason,
        "card": {
            "id": card.id, "name": card.name, "type": card.type, "numberMasked": masked_number(card),
            "expiry": card.expiry, "status": "active", "issuedAt": card.issued_at.isoformat(),
            "paymentAccount": payment_account(card), "paymentDay": card.payment_day,
            "limit": {"total": granted, "used": 0, "remaining": granted, "usageRate": 0.0} if granted else None,
            "debitLimit": debit_view(card) if card.type == "debit" else None,
        } if card else None,
        "estimatedDeliveryBusinessDays": {"min": 3, "max": 5} if card else None,
    }
    db.execute(update(m.IdempotencyKey).where(
        m.IdempotencyKey.user_id == user.id, m.IdempotencyKey.idem_key == key
    ).values(response_status=201, response_body=json.dumps(response, ensure_ascii=False)))
    db.commit()
    return response


# ───────────────────────── 07 해지 ─────────────────────────


def _termination_check(db: Session, c: m.Card) -> dict:
    if c.type == "debit":
        return {"cardId": c.id, "canTerminate": True, "blockReason": None, "unpaidAmount": 0, "firstDueDate": None}
    totals, today = totals_of(db, c), today_kst()
    unpaid = used_amount(totals, today)
    due = first_due_date(totals, today)
    return {"cardId": c.id, "canTerminate": unpaid == 0, "blockReason": "UNPAID_BALANCE" if unpaid else None,
            "unpaidAmount": unpaid, "firstDueDate": due.isoformat() if unpaid and due else None}


TERMINATE_ALLOWED = ["active", "suspended", "lost"]


@router.get("/cards/{card_id}/termination-check")
def termination_check(card_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    c = owned_card(db, user.id, card_id)
    if c.status == "terminated":
        raise state_invalid(c, TERMINATE_ALLOWED)
    return _termination_check(db, c)


@router.post("/cards/{card_id}/terminate")
def terminate_card(request: Request, card_id: str, body: dict = Depends(json_body), user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    fields: list[tuple[str, str]] = []
    reason = body.get("reason")
    if reason is not None and reason not in TERMINATE_REASONS:
        fields.append(("reason", "INVALID_ENUM"))
    if "acknowledged" not in body:
        fields.append(("acknowledged", "REQUIRED"))
    elif body["acknowledged"] is not True:
        fields.append(("acknowledged", "MUST_BE_TRUE"))
    if fields:
        raise validation(fields)
    card = owned_card(db, user.id, card_id)
    if card.status == "terminated":
        raise state_invalid(card, TERMINATE_ALLOWED)

    def blocked(check: dict) -> ApiError:
        return ApiError(409, "CARD_TERMINATE_BLOCKED_UNPAID", "미결제 금액이 있어 해지할 수 없습니다.",
                        {"unpaidAmount": check["unpaidAmount"], "firstDueDate": check["firstDueDate"]})

    if not (check := _termination_check(db, card))["canTerminate"]:
        raise blocked(check)
    require_pin_verified(request)

    db.rollback()  # 읽기 트랜잭션을 끝내고, 카드 행을 잠근 채 미결제 금액을 다시 계산한다
    card = db.scalar(select(m.Card).where(m.Card.id == card_id).with_for_update())
    if card.status == "terminated":
        db.rollback()
        raise state_invalid(card, TERMINATE_ALLOWED)
    if not (check := _termination_check(db, card))["canTerminate"]:
        db.rollback()
        raise blocked(check)
    from_status, now = card.status, now_utc()
    card.status, card.suspended_at, card.terminated_at, card.terminated_reason = "terminated", None, now, reason
    db.add(m.CardStatusHistory(card_id=card_id, user_id=user.id, action="terminate", from_status=from_status,
                               to_status="terminated", request_id=m.new_id("req")))
    db.commit()
    return {"id": card.id, "status": "terminated", "terminatedAt": iso(now)}
