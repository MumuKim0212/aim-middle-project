"""[역할] 대출관리(M01~M12): 계좌 조회·전체 상환 스케줄·중도상환·금리인하요구·청약철회·기간연장·증명서."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from decimal import Decimal as D

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession

from . import config as K
from .calculators import add_months, months_between, monthly_payment, schedule, to_won
from .database import Database, now_iso
from .errors import DuplicateRequest, NotFound, ValidationError
from .ids import new_id
from .security import sha256
from ..accounts import service as account_service

log = logging.getLogger("loan.management")


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


def _active(acc: dict, allowed: tuple[str, ...] = ("ACTIVE",)) -> None:
    if acc["status"] not in allowed:
        raise ValidationError("정상 상태의 대출에서만 할 수 있습니다.")


def _due_row(db: Database, acc: dict) -> tuple[int, dict]:
    """다음에 받을 회차: (이미 자동이체로 낸 회차 수, 그 회차의 원금·이자). 중도상환·기간연장이 반영된 현재 잔액 기준이다."""
    start = date.fromisoformat(acc["start_date"])
    done = db.one("SELECT COUNT(*) AS n FROM payment_txn WHERE contract_no = ? AND method = 'AUTO_DEBIT' AND result = 'DONE'", (acc["contract_no"],))["n"]
    return done, schedule(acc["balance"], D(str(acc["rate"])), max(acc["term_months"] - done, 1), acc["repay_method"], start, done)[0]


def late_penalty(acc: dict, principal: int, days: int) -> int:
    """지연배상금(M03) = 연체 원금 × (약정 금리 + 연 3%p, 법정 최고 금리 이내) × 연체 일수 / 365. 쌓아 두지 않고 일수로 계산하므로 하루에 두 번 붙지 않는다."""
    rate = min(D(str(acc["rate"])) + K.LATE_ADD, K.LEGAL_MAX_RATE)
    return to_won(D(principal) * rate / 100 * max(days, 0) / 365)


def overdue_info(db: Database, acc: dict) -> dict | None:
    """연체 중인 대출의 연체 현황(없으면 None): 연체 시작일·일수·단계, 미납 회차 금액, 지금 갚을 때의 지연배상금."""
    d = db.one("SELECT start_date, stage FROM delinquency WHERE contract_no = ? AND stage <> 'RESOLVED'", (acc["contract_no"],)) if acc["status"] == "OVERDUE" else None
    if d is None:
        return None
    today = account_service.today_kst()
    row = _due_row(db, acc)[1]
    penalty = late_penalty(acc, row["principal"], (today - date.fromisoformat(acc["next_due_date"])).days)
    return {"start_date": d["start_date"], "days": (today - date.fromisoformat(d["start_date"])).days, "stage": d["stage"],
            "installment": row["principal"] + row["interest"], "penalty": penalty, "total": row["principal"] + row["interest"] + penalty}


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


def prepay_quote(acc: dict, principal: int, db: Database | None = None) -> dict:
    """M05 견적: 수수료 = 원금 × 1.2% × 남은/전체 (3년 경과 면제), 경과 이자 15일(예시).
    연체 중 전액 상환이면 미납 회차의 지연배상금(penalty)을 더한다. shortcut: 일부 상환은 연체를 풀지 못하고 지연배상금도 받지 않는다(배치가 미납 회차를 받을 때 한 번 받는다)."""
    if principal <= 0 or principal > acc["balance"]:
        raise ValidationError("상환 원금은 0원보다 크고 잔액 이하여야 합니다.")
    el = months_between(date.fromisoformat(acc["start_date"]), date.today())
    rem = max(acc["term_months"] - el, 0)
    fee = 0 if el >= 36 else to_won(D(principal) * K.PREPAY_FEE_RATE * D(rem) / D(acc["term_months"]))
    interest = to_won(D(acc["balance"]) * D(str(acc["rate"])) / 100 * 15 / 365)
    info = overdue_info(db, acc) if db is not None and principal == acc["balance"] else None
    penalty = info["penalty"] if info else 0
    return {"principal": principal, "fee": fee, "interest": interest, "penalty": penalty, "total": principal + fee + interest + penalty, "fee_free": el >= 36}


def prepay(db: Database, contract_no: str, principal: int, idempotency_key: str, account_id: int | None = None) -> dict:
    """중도상환. 서버에서는 내 저축예금에서 총액을 출금한다(account_id, 없으면 대출의 자동이체 계좌)."""
    acc = account(db, contract_no)
    _active(acc, ("ACTIVE", "OVERDUE"))  # 연체 중에도 갚을 수 있다
    pay_from = account_id or acc["debit_account_id"]
    if acc["user_id"] is not None and pay_from is None:
        raise ValidationError("출금할 계좌를 선택해 주세요.")
    if db.one("SELECT 1 FROM prepay_request WHERE idempotency_key = ?", (idempotency_key,)):
        raise DuplicateRequest()
    q = prepay_quote(acc, principal, db)
    with db.tx():
        txn = account_service.loan_repay(db.session, acc["user_id"], pay_from, q["total"], contract_no, "대출 중도상환") if acc["user_id"] is not None else None
        db.insert("prepay_request", {"prepay_id": new_id("ppy"), "contract_no": contract_no, "principal": principal, "fee": q["fee"],
                                     "interest": q["interest"], "total": q["total"], "idempotency_key": idempotency_key, "executed_at": now_iso()})
        new_bal = acc["balance"] - principal
        db.update("loan_account", {"contract_no": contract_no}, {"balance": new_bal, "status": "PAID_OFF" if new_bal == 0 else acc["status"], "updated_at": now_iso()})
        db.insert("payment_txn", {"payment_id": new_id("pay"), "contract_no": contract_no, "due_date": date.today().isoformat(), "amount": q["total"],
                                  "allocation": {**({"penalty": q["penalty"]} if q["penalty"] else {}), "interest": q["interest"], "fee": q["fee"], "principal": principal},
                                  "method": "PREPAY", "result": "DONE", "account_txn_ref": txn, "paid_at": now_iso()})
        if new_bal == 0:
            db.execute("UPDATE collateral SET status = 'RELEASED', released_at = ? WHERE contract_no = ? AND status = 'SET'", (now_iso(), contract_no))
            _resolve_overdue(db, contract_no, account_service.today_kst())
        db.audit("loan_account", contract_no, "PREPAY", {"principal": principal})
    return {**q, "balance": new_bal}


def count_active_debit_loans(session: DbSession, account_id: int) -> int:
    """그 계좌를 자동이체 출금 계좌로 쓰는 진행 중 대출 수(공통.md 8장 인터페이스). 저축예금 해지 검사에 쓴다."""
    return Database(session).one("SELECT COUNT(*) AS n FROM loan_account WHERE debit_account_id = ? AND status IN ('ACTIVE', 'OVERDUE', 'ACCELERATED')",
                                 (account_id,))["n"]


OVERDUE_NOTICES = {"OVERDUE": "대출 상환금 출금에 실패해 연체 상태가 되었습니다. 지연배상금은 약정 금리에 연 3%p를 더한 율로 계산됩니다. 자동이체 계좌 잔액을 확인해 주세요.",
                   "OVERDUE_REMIND": "대출 연체가 5일 이상 이어지고 있습니다. 계속 연체되면 신용정보 등록 등 불이익이 있을 수 있습니다."}


def _mark_overdue(db: Database, acc: dict, due: str, installment: int, today: date) -> None:
    """미납 회차를 연체로 남긴다(M03): OVERDUE 전환, 해소 전까지 delinquency 1건을 매일 갱신(단계 D1·D5), 안내는 단계마다 한 번만 보낸다.
    shortcut: 기한의 이익 상실(ACCELERATED)과 그 사전 통지는 만들지 않는다(연체 단계 일수 기준 MMQ1 미정). 연체 일수는 달력 일수다(영업일 아님)."""
    no = acc["contract_no"]
    if acc["status"] != "OVERDUE":
        db.update("loan_account", {"contract_no": no}, {"status": "OVERDUE", "updated_at": now_iso()})
        db.audit("loan_account", no, "OVERDUE", {"due_date": due})
    d = db.one("SELECT delinquency_id, start_date, notices FROM delinquency WHERE contract_no = ? AND stage <> 'RESOLVED'", (no,))
    start = d["start_date"] if d else due
    days, notices = (today - date.fromisoformat(start)).days, json.loads(d["notices"]) if d else []
    for code in ["OVERDUE"] + (["OVERDUE_REMIND"] if days >= 5 else []):
        if code not in {n["code"] for n in notices}:
            notices.append({"code": code, "on": today.isoformat()})
            db.insert("notification", {"notification_id": new_id("ntf"), "user_id": acc["user_id"], "application_id": None, "contract_no": no,
                                       "event_code": code, "message": OVERDUE_NOTICES[code], "sent_at": now_iso()})
    row = {"days": days, "amount": installment, "stage": "D5" if days >= 5 else "D1", "notices": notices}
    if d:
        db.update("delinquency", {"delinquency_id": d["delinquency_id"]}, row)
    else:
        db.insert("delinquency", {"delinquency_id": new_id("dlq"), "contract_no": no, "start_date": due, **row})


def _resolve_overdue(db: Database, contract_no: str, today: date) -> None:
    """연체가 풀리면(전액 납부) 열린 delinquency 를 RESOLVED 로 닫는다. 열린 연체가 없으면 아무 일도 없다."""
    db.execute("UPDATE delinquency SET stage = 'RESOLVED', days = ?::date - start_date WHERE contract_no = ? AND stage <> 'RESOLVED'", (today, contract_no))


def _debit_one(db: Database, contract_no: str, today: date) -> bool:
    """납입일이 된 한 회차를 자동이체 계좌에서 출금한다. 출금하면 True, 할 일이 없거나 미납이면 False.
    ACTIVE 는 미납이면 OVERDUE 가 되고, OVERDUE 는 매 실행마다 다시 시도하며 지연배상금을 얹어 받는다. 미납이 모두 풀리면 ACTIVE 로 돌아온다."""
    acc = db.one("SELECT * FROM loan_account WHERE contract_no = ? FOR UPDATE", (contract_no,))  # 잠근 채 납입일을 넘기므로 같은 회차를 두 번 받지 않는다
    if acc["status"] not in ("ACTIVE", "OVERDUE") or acc["next_due_date"] is None or acc["next_due_date"] > today.isoformat() or acc["balance"] <= 0:
        return False
    due, start = acc["next_due_date"], date.fromisoformat(acc["start_date"])
    done, row = _due_row(db, acc)
    late = acc["status"] == "OVERDUE"
    penalty = late_penalty(acc, row["principal"], (today - date.fromisoformat(due)).days) if late else 0  # 서버가 꺼져 밀린 회차는 연체가 아니라 지연배상금이 없다
    amount = row["principal"] + row["interest"] + penalty
    try:
        with db.tx():
            txn = account_service.loan_repay(db.session, acc["user_id"], acc["debit_account_id"], amount, contract_no, "대출 자동이체")
    except HTTPException as e:  # 잔액 부족 등: 출금하지 않고 연체로 남긴다(납입일 그대로, 다음 실행에서 다시 시도)
        if not db.one("SELECT 1 FROM payment_txn WHERE contract_no = ? AND due_date = ? AND result = 'FAILED'", (contract_no, due)):
            db.insert("payment_txn", {"payment_id": new_id("pay"), "contract_no": contract_no, "due_date": due, "amount": amount,
                                      "allocation": {"reason": e.detail.get("code") if isinstance(e.detail, dict) else None}, "method": "AUTO_DEBIT",
                                      "result": "FAILED", "account_txn_ref": None, "paid_at": now_iso()})
        _mark_overdue(db, acc, due, row["principal"] + row["interest"], today)
        return False
    new_bal = acc["balance"] - row["principal"]
    next_due = None if new_bal == 0 else add_months(start, done + 2)
    cleared = late and (next_due is None or next_due > today)  # 밀린 회차를 다 냈다
    db.insert("payment_txn", {"payment_id": new_id("pay"), "contract_no": contract_no, "due_date": due, "amount": amount,
                              "allocation": {**({"penalty": penalty} if late else {}), "interest": row["interest"], "principal": row["principal"]}, "method": "AUTO_DEBIT",
                              "result": "DONE", "account_txn_ref": txn, "paid_at": now_iso()})
    db.update("loan_account", {"contract_no": contract_no}, {"balance": new_bal, "status": "PAID_OFF" if new_bal == 0 else "ACTIVE" if cleared else acc["status"],
                                                              "next_due_date": next_due.isoformat() if next_due else None, "updated_at": now_iso()})
    if cleared:
        _resolve_overdue(db, contract_no, today)
        db.audit("loan_account", contract_no, "OVERDUE_CLEARED", {"seq": done + 1})
    if new_bal == 0:
        db.execute("UPDATE collateral SET status = 'RELEASED', released_at = ? WHERE contract_no = ? AND status = 'SET'", (now_iso(), contract_no))
    db.audit("loan_account", contract_no, "AUTO_DEBIT", {"seq": done + 1, "amount": amount})
    return True


def auto_debit(session: DbSession, today: date | None = None) -> int:
    """월 상환 자동이체 배치: 납입일(next_due_date)이 지난 ACTIVE·OVERDUE 대출의 월 상환액을 자동이체 계좌에서 출금해 처리한 회차 수를 돌려준다.
    밀린 회차는 한 번에 따라잡고, 잔액이 모자라면 그 회차는 미납(연체)으로 두고 멈춘다. 대출 한 건의 실패가 다른 대출을 막지 않는다."""
    db, today = Database(session), today or account_service.today_kst()
    nos = [r["contract_no"] for r in db.all("SELECT contract_no FROM loan_account WHERE status IN ('ACTIVE', 'OVERDUE') AND user_id IS NOT NULL AND debit_account_id IS NOT NULL "
                                            "AND next_due_date <= ? ORDER BY contract_no", (today,))]
    paid = 0
    for no in nos:
        try:
            while _debit_one(db, no, today):
                paid += 1
            session.commit()
        except Exception:
            session.rollback()
            log.exception("대출 자동이체 실패 contract_no=%s", no)
    return paid


def change_auto_debit(db: Database, contract_no: str, user_id: int, account_id: int) -> dict:
    """M09: 자동이체 출금 계좌를 내 다른 저축예금으로 바꾼다. 바꾼 계좌는 다음 출금(연체 재시도 포함)부터 쓴다.
    shortcut: 납입일 직전 변경도 바로 적용한다(기획서는 2영업일 안이면 다음 회차부터). 출금 동의서(LN-08) 재작성은 하지 않고 간편비밀번호 재확인으로 갈음한다."""
    acc = account(db, contract_no, user_id)
    _active(acc, ("ACTIVE", "OVERDUE"))
    account_service.checking_for(db.session, user_id, account_id)  # 내 저축예금(active)만
    with db.tx():
        db.update("loan_account", {"contract_no": contract_no}, {"debit_account_id": account_id, "updated_at": now_iso()})
        db.execute("UPDATE loan_terms SET auto_debit_account_id = ?, updated_at = ? WHERE application_id = (SELECT application_id FROM contract WHERE contract_no = ?)",
                   (account_id, now_iso(), contract_no))
        db.audit("loan_account", contract_no, "AUTO_DEBIT_CHANGE", {"from": acc["debit_account_id"], "to": account_id})
    return {"contract_no": contract_no, "debit_account_id": account_id}


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
