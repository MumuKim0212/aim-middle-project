"""[역할] 빈 DB에 기준 데이터(상품·규제값·규칙·코드·양식·보증/협약/정책 기준·체험 고객)를 넣는다."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import catalog as C
from .database import Database, now_iso
from .scenarios import run_one
from .security import sha256


def seed(db: Database) -> None:
    """이미 들어 있으면 건너뛴다(여러 번 실행해도 안전)."""
    if db.one("SELECT 1 FROM product_catalog LIMIT 1"):
        return
    ts, today = now_iso(), date.today().isoformat()
    with db.tx():
        for i, title in enumerate(C.FORMS_LN, 1):
            no = f"LN-{i:02d}"
            db.insert("form_template", {"form_no": no, "service": "LOAN", "title": title, "file_name": f"Loan_Service/Contract_Document/{i:02d}_{title}.pdf", "version_hash": sha256(no + title)})
        for i, title in enumerate(C.FORMS_RF, 1):
            no = f"RF-{i:02d}"
            db.insert("form_template", {"form_no": no, "service": "REFI", "title": title, "file_name": f"Refinancing_Service/Contract_Document/{i:02d}_{title}.pdf", "version_hash": sha256(no + title)})
        for code, (title, req, form) in C.CONSENT_CODES.items():
            db.insert("consent_code", {"code": code, "title": title, "required_for": req, "form_no": form})
        for code, (grp, msg, fix) in C.REASON_CODES.items():
            db.insert("reason_code", {"code": code, "code_group": grp, "message": msg, "fixable": int(fix)})
        for i, p in enumerate(C.PRODUCTS):
            pid, btype, kind, cat, sub, name, mx, mn, rmin, rmax, terms, repay, target = p
            db.insert("product_catalog", {"product_id": pid, "business_type": btype, "inst_kind": kind, "collateral_type": cat,
                                          "sort_no": i, "name": name, "subtitle": sub, "target_desc": target, "max_amount": mx, "min_amount": mn,
                                          "rate_min": rmin, "rate_max": rmax, "term_options": terms, "repay_options": repay,
                                          "rules": {}, "sale_from": "2026-01-01", "sale_to": None, "version": 1, "created_at": ts})
        for key, val, unit, desc in C.REG_PARAMS:
            db.insert("reg_param", {"param_key": key, "version": 1, "value": val, "unit": unit, "description": desc,
                                    "effective_from": "2026-01-01", "effective_to": None, "approved_by": "준법감시(예시)", "created_at": ts})
        for rid in C.RULES:
            db.insert("rule_version", {"rule_id": rid, "version": 1, "rule_type": rid.split("-")[0], "body": {"source": "프로토타입_구현명세.md"},
                                       "effective_from": "2026-01-01", "effective_to": None, "approved_by": "준법감시(예시)", "created_at": ts})
        for agency, fee, cap in C.GUARANTEE_RULES:
            db.insert("guarantee_rule", {"agency": agency, "version": 1, "fee_rate": fee, "cap_amount": cap, "max_ratio": "0.90", "effective_from": "2026-01-01"})
        for oid, name in C.ORGS:
            db.insert("agreement_org", {"org_id": oid, "name": name, "conditions": {"employment_type": ["정규직"]}, "rate_table": {"add": "0.4", "score_cut": 800},
                                        "total_limit": 50_000_000_000, "used_limit": 0, "valid_from": "2026-01-01", "valid_to": "2030-12-31"})
        for pid, rule in C.POLICY_RULES.items():
            db.insert("policy_rule", {"policy_id": f"POL-{pid}", "version": 1, "product_id": pid, "items": rule,
                                      "rate_table": {"over_6000": "0.5", "over_4000": "0.25"}, "obligations": C.OBLIGATIONS,
                                      "effective_from": "2026-01-01", "effective_to": None, "approved_by": "정책기관 공고(예시)"})
        for uc, tier, desc in C.PROMPTS:
            db.insert("prompt_registry", {"use_case_id": uc, "version": 1, "model_tier": tier, "template": desc,
                                          "output_schema": {"type": "object", "required": ["reasons", "cautions", "cited_facts"]},
                                          "timeout_ms": 3000, "created_at": ts})
        for key, s in C.SCENARIOS.items():
            db.insert("demo_scenario", {"scenario_key": key, "label": s["label"], "profile": s["profile"],
                                        "existing_loans": s["loans"], "defects": s["defects"]})
        db.audit("system", "seed", "SEED", {"date": today})


DEMO_LOANS = [("g1", "KIM_OK"), ("r1", "KIM_OK")]  # 화면 시연용 내 대출(신용대출 1건, 대환 1건)


def setup(session: Session, demo_user_id: int) -> None:
    """서버 시작 때 호출한다: 대출 기준 데이터를 넣고(테이블은 Alembic 이 만든다), 시연 회원에게 대출 2건을 만들어 준다.
    시연 대출은 실제 신청 흐름(체험 고객 KIM_OK)을 그대로 실행해 만든다. 계좌 입금은 하지 않아 계좌 시드 잔액을 바꾸지 않는다."""
    db = Database(session)
    seed(db)
    if not db.one("SELECT 1 FROM loan_account WHERE user_id = ?", (demo_user_id,)):
        for pid, scn in DEMO_LOANS:
            run_one(db, pid, scn, user_id=demo_user_id)
    session.commit()
