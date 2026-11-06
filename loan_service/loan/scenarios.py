"""[역할] 체험 고객 × 상품 21개 조합을 처음부터 끝까지 자동 실행해 정답표(구현명세 11장)와 비교한다."""
from __future__ import annotations

from .application import Session
from .database import Database
from .errors import LoanError

# (상품, 체험 고객, 기대 결과) — 구현명세 11장
EXPECTED = [
    ("g1", "KIM_OK", "APPROVED"), ("g1", "KIM_BAD", "REJECTED"), ("g2", "PARK_OK", "APPROVED"), ("g2", "PARK_BAD", "REJECTED"),
    ("g3", "NAM_OK", "APPROVED"), ("g3", "NAM_BAD", "REJECTED"), ("g4", "LIM_OK", "APPROVED"), ("g4", "LIM_BAD", "REJECTED"),
    ("g5", None, "APPROVED"), ("p1", "KIM_OK", "APPROVED"), ("p2", "PARK_OK", "APPROVED"), ("i1", "PARK_OK", "APPROVED"),
    ("i2", "KIM_OK", "APPROVED"), ("r1", "KIM_OK", "BENEFICIAL"), ("r1", "KIM_BAD", "REFI_INELIGIBLE"), ("r3", "PARK_OK", "TRADE_OFF"),
    ("r3", "PARK_BAD", "REFI_INELIGIBLE"), ("r2", "NAM_OK", "BENEFICIAL"), ("r2", "NAM_BAD", "REFI_INELIGIBLE"), ("r4", "LIM_OK", "BENEFICIAL"),
    ("r4", "LIM_BAD", "REFI_INELIGIBLE"),
]


def run_one(db: Database, pid: str, scn: str | None, complete: bool = True) -> dict:
    """한 조합 실행. 승인이면 약정·실행까지 진행해 대출 계좌를 만든다."""
    s = Session.start(db, pid, scn)
    out = {"product": pid, "scenario": scn or "NONE", "codes": []}
    try:
        if s.product["business_type"] == "POLICY":
            s.precheck(True, False, s.scenario["profile"]["income"] if s.scenario else 50_000_000, 200_000_000)
        s.give_consents({c: True for c in s.required_consents()})
        if s.refi:
            s.fetch_existing()
            if not s.select_targets():
                out["result"] = "REFI_INELIGIBLE"
                out["codes"] = sorted({c for e in s.existing for c in e["codes"]})
                return out
        res, _, _ = s.submit_profile({}, ack_unsuitable=True)
        if s.product["business_type"] == "POLICY" and not s.policy_check():
            out["result"] = "POLICY_INELIGIBLE"
            return out
        if s.flow_key == "INST_A" and not s.choose_guarantee():
            out["result"] = "GUARANTEE_REJECTED"
            return out
        if s.flow_key == "INST_B" and not s.affiliation("ORG02", "A123456", "정규직"):
            out["result"] = "AFFILIATION_FAILED"
            return out
        s.submit_docs()
        r = s.run_review()
        out["limit"], out["codes"] = r.limit, r.hard
        out["result"] = r.result
        if r.result in ("REJECTED", "DOCS_REQUIRED"):
            return out
        if s.refi:
            cmp = s.compare(confirm_unfavorable=True)
            out["result"] = cmp["verdict"]
            out["net"] = cmp["net"]
        else:
            cands = s.recommend()
            s.choose(cands[0])
        if complete:
            s.set_terms()
            s.price()
            s.explain(True, [a for _, a in s.quiz()])
            s.sign_contract([True] * 5)
            if s.needs_collateral():
                s.set_collateral()
            s.execute(f"exec:{s.app_id}")
            out["contract"] = s.contract
    except LoanError as e:
        out["result"] = f"ERROR: {e.user_message}"
    return out


def run_all(db: Database, complete: bool = True) -> list[dict]:
    rows = []
    for pid, scn, expect in EXPECTED:
        r = run_one(db, pid, scn, complete)
        r["expected"] = expect
        r["match"] = r["result"] == expect
        rows.append(r)
    return rows
