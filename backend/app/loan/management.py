"""[역할] 대출관리(M01~M12): 계좌 조회·전체 상환 스케줄·중도상환·금리인하요구·청약철회·기간연장·증명서."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from . import config as K
from .calculators import months_between, monthly_payment, schedule, to_won
from .database import Database, now_iso
from .errors import DuplicateRequest, NotFound, ValidationError
from .ids import new_id
from .security import sha256
from ..accounts import service as account_service


def accounts(db: Database, user_id: int | None = None) -> list[dict]:
    """user_id 를 주면 그 회원의 대출만(서버), 없으면 전부(콘솔·시험)."""
    rows = db.all("""SELECT a.*, p.name AS product_name, p.business_type FROM loan_account a
                     JOIN product_catalog p ON p.product_id = a.product_id
                     WHERE (?::bigint IS NULL OR a.user_id = ?) ORDER BY a.start_date DESC, a.updated_at DESC, a.contract_no DESC""", (user_id, user_id))
    return [dict(r) for r in rows]


def account(db: Database, contract_no: str, user_id: int | None = None) -> dict:
    """내 대출만 찾는다. 없는 계약과 타인의 계약은 똑같이 NotFound 다(공통.md 3장)."""
    r = db.one("SELECT * FROM loan_account WHERE contract_no = ? AND (?::bigint IS NULL OR user_id = ?)", (contract_no, user_id, user_id))
    if r is None:
        raise NotFound("대출 계좌를 찾을 수 없습니다.")
    return dict(r)


def _active(acc: dict) -> None:
    if acc["status"] != "ACTIVE":
        raise ValidationError("정상 상태의 대출에서만 할 수 있습니다.")


def card_monthly(acc: dict) -> int:
    """카드 '월 납입' = 그 대출 상환 방법의 월 상환액(최초 대출금, 금리, 현재 기간)."""
    return to_won(monthly_payment(acc["principal"], D(str(acc["rate"])), acc["term_months"], acc["repay_method"]))


def full_schedule(acc: dict) -> dict:
    """M01: 현재 잔액에서 잔액 0원까지 남은 회차 전부(구현명세·대출관리 M01 규칙)."""
    start = date.fromisoformat(acc["start_date"])
    paid = min(max(months_between(start, date.today()), 0), acc["term_months"] - 1)
    remain = max(acc["term_months"] - paid, 1)
    rows = schedule(acc["balance"], D(str(acc["rate"])), remain, acc["repay_method"], start, paid) if acc["balance"] > 0 else []
    return {"paid": paid, "rows": rows, "principal_sum": sum(r["principal"] for r in rows), "interest_sum": sum(r["interest"] for r in rows)}


def prepay_quote(acc: dict, principal: int) -> dict:
    """M05 견적: 수수료 = 원금 × 1.2% × 남은/전체 (3년 경과 면제), 경과 이자 15일(예시)."""
    if principal <= 0 or principal > acc["balance"]:
        raise ValidationError("상환 원금은 0원보다 크고 잔액 이하여야 합니다.")
    el = months_between(date.fromisoformat(acc["start_date"]), date.today())
    rem = max(acc["term_months"] - el, 0)
    fee = 0 if el >= 36 else to_won(D(principal) * K.PREPAY_FEE_RATE * D(rem) / D(acc["term_months"]))
    interest = to_won(D(acc["balance"]) * D(str(acc["rate"])) / 100 * 15 / 365)
    return {"principal": principal, "fee": fee, "interest": interest, "total": principal + fee + interest, "fee_free": el >= 36}


def prepay(db: Database, contract_no: str, principal: int, idempotency_key: str, account_id: int | None = None) -> dict:
    """중도상환. 서버에서는 내 저축예금에서 총액을 출금한다(account_id, 없으면 대출의 자동이체 계좌)."""
    acc = account(db, contract_no)
    _active(acc)
    pay_from = account_id or acc["debit_account_id"]
    if acc["user_id"] is not None and pay_from is None:
        raise ValidationError("출금할 계좌를 선택해 주세요.")
    if db.one("SELECT 1 FROM prepay_request WHERE idempotency_key = ?", (idempotency_key,)):
        raise DuplicateRequest()
    q = prepay_quote(acc, principal)
    with db.tx():
        txn = account_service.loan_repay(db.session, acc["user_id"], pay_from, q["total"], contract_no, "대출 중도상환") if acc["user_id"] is not None else None
        db.insert("prepay_request", {"prepay_id": new_id("ppy"), "contract_no": contract_no, "principal": principal, "fee": q["fee"],
                                     "interest": q["interest"], "total": q["total"], "idempotency_key": idempotency_key, "executed_at": now_iso()})
        new_bal = acc["balance"] - principal
        db.update("loan_account", {"contract_no": contract_no}, {"balance": new_bal, "status": "PAID_OFF" if new_bal == 0 else "ACTIVE", "updated_at": now_iso()})
        db.insert("payment_txn", {"payment_id": new_id("pay"), "contract_no": contract_no, "due_date": date.today().isoformat(), "amount": q["total"],
                                  "allocation": {"interest": q["interest"], "fee": q["fee"], "principal": principal}, "method": "PREPAY",
                                  "result": "DONE", "account_txn_ref": txn, "paid_at": now_iso()})
        if new_bal == 0:
            db.execute("UPDATE collateral SET status = 'RELEASED', released_at = ? WHERE contract_no = ? AND status = 'SET'", (now_iso(), contract_no))
        db.audit("loan_account", contract_no, "PREPAY", {"principal": principal})
    return {**q, "balance": new_bal}


def rate_cut(db: Database, contract_no: str, reasons: list[str]) -> dict:
    """M06: 사유 1개 이상 필수. 프로토타입 기준 현재 금리 > 4.5%면 −0.3%p 수용."""
    if not reasons:
        raise ValidationError("사유를 하나 이상 선택하세요.")
    acc = account(db, contract_no)
    _active(acc)
    old = D(str(acc["rate"]))
    ok = old > K.RATE_CUT_THRESHOLD
    new = (old - K.RATE_CUT_STEP).quantize(D("0.01")) if ok else None
    with db.tx():
        db.insert("rate_cut_request", {"rate_cut_id": new_id("rcr"), "contract_no": contract_no, "reasons": reasons,
                                       "result": "ACCEPTED" if ok else "REJECTED", "new_rate": str(new) if new else None,
                                       "requested_at": now_iso(), "notified_at": now_iso()})
        if ok:
            db.update("loan_account", {"contract_no": contract_no}, {"rate": str(new), "updated_at": now_iso()})
            db.insert("rate_change", {"rate_change_id": new_id("rch"), "contract_no": contract_no, "effective_date": date.today().isoformat(),
                                      "old_rate": str(old), "new_rate": str(new), "reason": "RATE_CUT"})
    return {"accepted": ok, "new_rate": new, "old_rate": old}


def withdraw(db: Database, contract_no: str) -> dict:
    """M07: 실행일 + 14일 이내만. 대출금 + 약정 이자(3일, 예시) + 부대비용 반환."""
    acc = account(db, contract_no)
    _active(acc)
    deadline = date.fromisoformat(acc["start_date"]) + timedelta(days=K.WITHDRAW_DAYS)
    ok = date.today() <= deadline
    refund = acc["principal"] + to_won(D(acc["principal"]) * D(str(acc["rate"])) / 100 * 3 / 365) + (K.STAMP_DUTY_CUSTOMER if acc["principal"] > K.STAMP_DUTY_THRESHOLD else 0)
    with db.tx():
        if ok and acc["user_id"] is not None:  # 받은 대출금이 들어간 내 계좌에서 되돌려 받는다. 잔액이 모자라면 철회가 거부된다
            dsb = db.one("SELECT account_id FROM disbursement WHERE contract_no = ? AND account_id IS NOT NULL", (contract_no,))
            if dsb:
                account_service.loan_repay(db.session, acc["user_id"], dsb["account_id"], refund, contract_no, "대출 청약철회 반환")
        db.insert("withdrawal_request", {"withdrawal_id": new_id("wdr"), "contract_no": contract_no, "deadline": deadline.isoformat(),
                                         "refund_total": refund, "status": "ACCEPTED" if ok else "REFUSED", "requested_at": now_iso()})
        if ok:
            db.update("loan_account", {"contract_no": contract_no}, {"status": "WITHDRAWN", "updated_at": now_iso()})
    return {"accepted": ok, "deadline": deadline, "refund": refund}


def extend(db: Database, contract_no: str, months: int) -> dict:
    if months not in (12, 24):
        raise ValidationError("연장 기간은 12개월 또는 24개월입니다.")
    acc = account(db, contract_no)
    _active(acc)
    new_term = acc["term_months"] + months
    with db.tx():
        db.insert("term_change_request", {"term_change_id": new_id("tcr"), "contract_no": contract_no, "items": {"extend": months},
                                          "result": "APPROVED", "new_term": new_term, "requested_at": now_iso()})
        db.update("loan_account", {"contract_no": contract_no}, {"term_months": new_term, "updated_at": now_iso()})
    return {"new_term": new_term}


def certificate(db: Database, contract_no: str, cert_type: str) -> str:
    acc = account(db, contract_no)
    if cert_type not in ("BALANCE", "INTEREST", "PAYOFF"):
        raise ValidationError("증명서 종류를 확인해 주세요.")
    if cert_type == "PAYOFF" and acc["status"] != "PAID_OFF":
        raise ValidationError("완제 확인서는 완제된 대출만 발급할 수 있습니다.")
    cert_no = f"CT-{contract_no}-{ {'BALANCE': 1, 'INTEREST': 2, 'PAYOFF': 3}[cert_type] }-{new_id('c')[-6:]}"
    db.insert("certificate", {"cert_no": cert_no, "contract_no": contract_no, "cert_type": cert_type,
                              "doc_hash": sha256(f"{cert_no}|{acc['balance']}"), "issued_at": now_iso()})
    return cert_no
