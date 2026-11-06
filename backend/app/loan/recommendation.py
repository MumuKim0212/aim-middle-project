"""[역할] 권장 상품 산출·순위·검증(main 7장): 3가지 금리 안 → 고객 이익 점수 → LLM 사유 → V1~V9 검증 → 기록."""
from __future__ import annotations

import re
from decimal import Decimal as D

from .calculators import kwon, monthly_payment, to_won, total_interest
from .database import Database, now_iso
from .ids import new_id
from .llm_gateway import generate

VARIANTS = [("비대면 전용형", D("-0.15"), "변동"), ("변동금리형", D("0"), "변동"), ("고정금리형", D("0.3"), "고정")]


def _nums(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out |= set(re.findall(r"\d[\d,]*(?:\.\d+)?", t))
    return out


def recommend(db: Database, application_id: str, product, amount: int, term: int, repay: str, base_rate: D,
              income: int, rate_pref: str) -> list[dict]:
    """같은 상품의 금리 유형 3안을 고객 비용 기준으로 정렬. 은행 수익성은 점수에 넣지 않는다."""
    cands = []
    for name, delta, rtype in VARIANTS:
        r = (base_rate + delta).quantize(D("0.01"))
        ti, m = total_interest(amount, r, term, repay), monthly_payment(amount, r, term, repay)
        pref = D(1) if (rate_pref == "상관없음" or rate_pref.startswith(rtype)) else D("0.2")
        cands.append({"variant": name, "rate": r, "rate_type": rtype, "total_interest": to_won(ti), "monthly": to_won(m), "pref": pref})
    tis = [c["total_interest"] for c in cands]
    mn, mx = min(tis), max(tis)
    monthly_income = max(D(income) / 12, D(1))
    for c in cands:
        f_cost = 1 - D(c["total_interest"] - mn) / D(mx - mn + 1)
        f_burden = 1 - min(D(c["monthly"]) / monthly_income / D("0.7"), D(1))
        c["score"] = (D("0.4") * f_cost + D("0.2") + D("0.15") * f_burden + D("0.1") * c["pref"] + D("0.15")).quantize(D("0.0001"))
    cands.sort(key=lambda c: c["score"], reverse=True)

    # LLM-8 사유 생성 + 검증
    facts = {"candidates": []}
    for c in cands:
        diff = c["total_interest"] - cands[0]["total_interest"]
        facts["candidates"].append({"variant": c["variant"], "rate_type": c["rate_type"], "rate_text": f"{c['rate']}",
                                    "total_interest_text": kwon(c["total_interest"]), "is_min": c["total_interest"] == mn,
                                    "diff_text": kwon(abs(diff)), "diff_sign": 1 if diff >= 0 else -1})
    allowed = _nums(*[str(v) for f in facts["candidates"] for k, v in f.items() if k.endswith("_text")])
    fallback = {"items": [{"product_id": c["variant"], "reasons": ["후보 상품 중 하나입니다."], "cautions": ["금리 변동 위험을 확인하세요."], "cited_facts": []} for c in cands]}
    res = generate(db, application_id, "LLM-8", facts, allowed_numbers=allowed, allowed_ids={c["variant"] for c in cands},
                   required_phrases=["월 상환액"], fallback=fallback)
    reasons = {it["product_id"]: it for it in res.output["items"]}
    checks = {**res.validation,
              "V4_cited": all(any(cf.get("value") == f"{c['rate']}" for cf in reasons.get(c["variant"], {}).get("cited_facts", [])) or res.fallback_used for c in cands),
              "V7_order": [c["variant"] for c in cands] == [it["product_id"] for it in res.output["items"]],
              "V8_recalc": all(to_won(total_interest(amount, c["rate"], term, repay)) == c["total_interest"] for c in cands),
              "V9_suitable": all(D(c["monthly"]) / monthly_income <= D("0.7") for c in cands)}
    for c in cands:
        it = reasons.get(c["variant"], {})
        c["reasons"], c["cautions"] = it.get("reasons", []), it.get("cautions", [])
    db.insert("recommendation_log", {"recommendation_id": new_id("rec"), "application_id": application_id,
                                     "candidates": [{k: str(v) for k, v in c.items() if k not in ("reasons", "cautions")} for c in cands],
                                     "scores": {c["variant"]: str(c["score"]) for c in cands}, "chosen_variant": None,
                                     "weights_version": "REC-WEIGHTS@1", "llm_call_id": res.call_id, "validation": checks,
                                     "displayed_text": " / ".join(" ".join(c["reasons"]) for c in cands), "created_at": now_iso()})
    return cands
