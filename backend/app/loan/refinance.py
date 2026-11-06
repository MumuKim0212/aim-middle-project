"""[역할] 대환 로직(R03~R16): 기존 대출 조회·대환 자격·유불리 계산·사가 실행(실패 시 보상 거래)·완제 확인."""
from __future__ import annotations

from decimal import Decimal as D

from . import config as K
from .calculators import kwon, monthly_payment, to_won, total_interest
from .database import Database, now_iso
from .errors import SagaFailed
from .ids import new_id
from .llm_gateway import _numbers, generate
from .security import keyed_hash, mask_account


def eligibility(loan: dict) -> list[str]:
    """REFI-ELIG: 연체·실행 후 6개월 미만·가압류·남은 6개월 미만·담보 불일치."""
    f = loan.get("flags", {})
    codes = []
    if f.get("delinq"):
        codes.append("REFI-DELINQ")
    if loan["since"] < K.REFI_MIN_SINCE:
        codes.append("REFI-TOO-RECENT")
    if f.get("legal"):
        codes.append("REFI-LEGAL-HOLD")
    if loan["remain"] < K.REFI_MIN_REMAIN:
        codes.append("REFI-SHORT-REMAIN")
    if f.get("asset_mismatch"):
        codes.append("ASSET-MISMATCH")
    return codes


def prepay_fee(loan: dict) -> int:
    if loan["since"] >= K.REFI_FEE_FREE_MONTHS:
        return 0
    return to_won(D(loan["balance"]) * D(loan["prepay"]) / 100 * D(loan["remain"]) / D(loan["total"]))


def save_existing(db: Database, application_id: str, loans: list[dict], source: str = "MYDATA") -> list[dict]:
    """조회한 기존 대출 저장(계좌번호 원문은 저장하지 않고 마스킹·해시만)."""
    out = []
    for i, ln in enumerate(loans):
        acct = f"{100 + i}-{200000 + i:06d}-{30000 + i:05d}"          # 데모용 가상 번호
        lid = new_id("exl")
        db.insert("existing_loan", {"existing_loan_id": lid, "application_id": application_id, "source": source,
                                    "institution": ln["institution"], "kind": ln["kind"], "account_masked": mask_account(acct),
                                    "account_hash": keyed_hash(acct), "balance": ln["balance"], "rate": ln["rate"],
                                    "since_months": ln["since"], "remain_months": ln["remain"], "total_months": ln["total"],
                                    "monthly_payment": ln["monthly"], "prepay_fee_rate": ln["prepay"], "is_bullet": int(ln["bullet"]),
                                    "flags": ln.get("flags", {}), "fetched_at": now_iso()})
        codes = eligibility(ln)
        db.insert("refi_target", {"refi_target_id": new_id("rft"), "application_id": application_id, "existing_loan_id": lid,
                                  "eligible": int(not codes), "reason_codes": codes, "selected": int(not codes)})
        out.append({**ln, "id": lid, "codes": codes})
    return out


def refi_amount(targets: list[dict]) -> int:
    """대환 금액 = Σ(잔액 + 중도상환수수료). 인지세는 금액에 넣지 않는다(구현명세 14장)."""
    return sum(t["balance"] + prepay_fee(t) for t in targets)


def benefit(db: Database, application_id: str, product, targets: list[dict], new_rate: D, term: int, repay: str) -> dict:
    """유불리: 순 절감액 = 기존 남은 이자 − 새 총 이자 − 대환 비용. 판정은 순 절감액 기준."""
    bal = sum(t["balance"] for t in targets)
    fee = sum(prepay_fee(t) for t in targets)
    stamp = K.STAMP_DUTY_CUSTOMER if bal > K.STAMP_DUTY_THRESHOLD else 0
    cost = fee + stamp
    old_int = sum(to_won(D(t["balance"]) * D(t["rate"]) / 1200 * t["remain"]) if t["bullet"]
                  else to_won(total_interest(t["balance"], D(t["rate"]), t["remain"], "원리금균등분할")) for t in targets)
    principal = refi_amount(targets)
    new_int = to_won(total_interest(principal, new_rate, term, repay))
    old_m = sum(t["monthly"] for t in targets)
    new_m = to_won(monthly_payment(principal, new_rate, term, repay))
    net = old_int - new_int - cost
    be, acc = None, 0
    for m in range(1, term + 1):
        acc += old_m - new_m
        if acc >= cost:
            be = m
            break
    verdict = "BENEFICIAL" if net > 0 else ("TRADE_OFF" if old_m - new_m > 0 else "NOT_BENEFICIAL")
    old_rate = (sum(D(t["rate"]) * t["balance"] for t in targets) / bal).quantize(D("0.01"))
    data = {"old_interest": old_int, "new_interest": new_int, "cost": cost, "fee": fee, "stamp": stamp, "net": net,
            "break_even": be, "old_monthly": old_m, "new_monthly": new_m, "verdict": verdict, "old_rate": old_rate,
            "new_rate": new_rate, "term": term, "remain": max(t["remain"] for t in targets), "principal": principal}
    facts = {"verdict": verdict, "net_text": kwon(net), "cost_text": kwon(cost)}
    res = generate(db, application_id, "RLLM-3", facts, allowed_numbers=_numbers(facts["net_text"] + " " + facts["cost_text"]), allowed_ids={"REFI"},
                   required_phrases=["대환 비용"], fallback={"items": [{"product_id": "REFI", "reasons": [f"판정: {verdict}"], "cautions": ["대환 비용을 확인하세요."], "cited_facts": []}]})
    data["message"] = res.output["items"][0]
    db.insert("refi_benefit", {"benefit_id": new_id("rfb"), "application_id": application_id, "product_id": product["product_id"],
                               "new_term": term, "old_remaining_interest": old_int, "new_total_interest": new_int,
                               "cost": {"prepay_fee": fee, "stamp_duty": stamp}, "net_saving": net, "break_even_month": be,
                               "monthly_change": old_m - new_m, "verdict": verdict, "calc_version": "REFI-BENEFIT@1", "created_at": now_iso()})
    return data


def execute_saga(db: Database, application_id: str, contract_no: str, targets: list[dict], fail_at: str | None = None) -> dict:
    """R15 사가: ①상환 금액 확정 ②새 대출 실행(지급 보류) ③송금+상환 요청 ④완제 확인.
    중간에 실패하면 이미 끝난 단계를 거꾸로 되돌리고(보상 거래) SagaFailed를 낸다."""
    saga_id, steps, comp = new_id("sag"), [], []
    db.insert("saga_instance", {"saga_id": saga_id, "application_id": application_id, "saga_type": "REFI_EXECUTE",
                                "status": "RUNNING", "steps": [], "compensation": [], "started_at": now_iso(), "finished_at": None})
    try:
        for t in targets:                                                         # ① 실행일 상환 금액 확정
            fee = prepay_fee(t)
            db.insert("payoff_quote", {"quote_id": new_id("poq"), "application_id": application_id, "existing_loan_id": t["id"],
                                       "principal": t["balance"], "interest": 0, "prepay_fee": fee, "total": t["balance"] + fee,
                                       "valid_until": now_iso(), "quoted_at": now_iso()})
        steps.append("QUOTE")
        if fail_at == "EXECUTE":
            raise RuntimeError("core banking down")
        steps.append("EXECUTE_HOLD")                                              # ② 지급 보류 상태 실행
        comp.append("CANCEL_LOAN")
        if fail_at == "TRANSFER":
            raise RuntimeError("transfer failed")
        for t in targets:                                                         # ③ 송금 + 상환 요청
            db.insert("disbursement", {"disbursement_id": new_id("dsb"), "contract_no": contract_no, "payee_type": "PAYOFF",
                                       "payee_masked": t["institution"], "account_id": None, "account_txn_ref": None,
                                       "amount": t["balance"] + prepay_fee(t), "result": "DONE",
                                       "idempotency_key": f"{contract_no}:payoff:{t['id']}", "executed_at": now_iso()})
        steps.append("TRANSFER")
        comp.append("RETURN_TRANSFER")
        if fail_at == "CONFIRM":
            raise RuntimeError("payoff not confirmed")
        for t in targets:                                                         # ④ 완제 확인
            db.insert("payoff_record", {"payoff_id": new_id("pof"), "existing_loan_id": t["id"], "contract_no": contract_no,
                                        "paid_amount": t["balance"] + prepay_fee(t), "result": "PAID_OFF",
                                        "paid_at": now_iso(), "confirmed_at": now_iso()})
        steps.append("CONFIRM")
        db.update("saga_instance", {"saga_id": saga_id}, {"status": "DONE", "steps": steps, "finished_at": now_iso()})
        return {"saga_id": saga_id, "steps": steps}
    except Exception as exc:
        for c in reversed(comp):                                                  # 보상 거래(역순)
            if c == "RETURN_TRANSFER":
                db.execute("UPDATE disbursement SET result = 'CANCELLED' WHERE contract_no = ? AND payee_type = 'PAYOFF'", (contract_no,))
        db.update("saga_instance", {"saga_id": saga_id}, {"status": "COMPENSATED", "steps": steps, "compensation": list(reversed(comp)), "finished_at": now_iso()})
        db.audit("saga_instance", saga_id, "COMPENSATED", {"failed_at": fail_at or type(exc).__name__})
        raise SagaFailed(detail=str(exc)) from exc
