"""[역할] LLM 게이트웨이(main 8장): 마스킹→생성→출력 검증(스키마·수치·금지어·필수 문구)→실패 시 템플릿 대체·기록."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from . import config
from .database import Database, dumps, now_iso
from .errors import GuardrailViolation
from .ids import new_id
from .security import mask_pii, sha256

BANNED = ["무조건", "100%", "반드시 승인", "승인 확정", "최저 금리 보장", "손해 없", "동의하시는 게 좋", "틀림없이"]


@dataclass
class LlmResult:
    output: dict
    fallback_used: bool
    validation: dict = field(default_factory=dict)
    call_id: str = ""


class OfflineProvider:
    """외부 호출 없이 입력 사실만으로 문장을 만드는 기본 제공자(데모·장애 시 대체)."""

    name = "offline"

    def complete(self, use_case: str, facts: dict) -> str:
        if use_case == "LLM-8":
            items = []
            for i, c in enumerate(facts["candidates"]):
                if i == 0:
                    lead = (f"후보 중 총 이자가 가장 적습니다(약 {c['total_interest_text']})." if c["is_min"]
                            else f"추천 점수가 가장 높습니다(총 이자 약 {c['total_interest_text']}).")
                else:
                    lead = f"총 이자는 첫 번째 추천안보다 약 {c['diff_text']} {'많습니다' if c['diff_sign'] >= 0 else '적습니다'}."
                caution = "변동금리는 시장 금리가 오르면 월 상환액이 늘 수 있습니다." if c["rate_type"] == "변동" else "금리가 고정되어 월 상환액이 바뀌지 않습니다."
                items.append({"product_id": c["variant"], "reasons": [lead], "cautions": [caution],
                              "cited_facts": [{"field": "final_rate", "value": c["rate_text"]}]})
            return json.dumps({"items": items}, ensure_ascii=False)
        if use_case == "RLLM-3":
            v = {"BENEFICIAL": "갈아타면 이득입니다.", "TRADE_OFF": "월 부담은 줄지만 총 이자는 늘어납니다.", "NOT_BENEFICIAL": "갈아타면 손해입니다."}[facts["verdict"]]
            return json.dumps({"items": [{"product_id": "REFI", "reasons": [f"{v} 순 절감액 {facts['net_text']}."],
                                          "cautions": [f"대환 비용(중도상환수수료 등) {facts['cost_text']}이 포함된 계산입니다."],
                                          "cited_facts": [{"field": "net_saving", "value": facts["net_text"]}]}]}, ensure_ascii=False)
        return json.dumps({"items": [{"product_id": "-", "reasons": [facts.get("text", "")], "cautions": [], "cited_facts": []}]}, ensure_ascii=False)


class ExternalProviderNotConfigured(OfflineProvider):
    """외부 LLM은 자체 게이트웨이 API 뒤에서만 연결한다(main 8.4~8.6). 키·계약이 없으면 쓰지 않는다."""

    name = "external"

    def complete(self, use_case: str, facts: dict) -> str:
        raise GuardrailViolation(detail="external LLM provider not configured")


def _provider():
    return OfflineProvider() if config.LLM_PROVIDER == "offline" else ExternalProviderNotConfigured()


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,]*(?:\.\d+)?", text))


def validate(output_text: str, allowed_numbers: set[str], allowed_ids: set[str], required_phrases: list[str]) -> dict:
    """V1 스키마 · V2 대상 실재 · V3 수치 일치 · V5 금지 표현 · V6 필수 문구."""
    res = {"V1_schema": False, "V2_exists": False, "V3_numbers": False, "V5_banned": False, "V6_required": False}
    try:
        data = json.loads(output_text)
        items = data["items"]
        ok = isinstance(items, list) and all(isinstance(i, dict) and {"product_id", "reasons", "cautions", "cited_facts"} <= set(i) for i in items)
        res["V1_schema"] = bool(ok)
    except (ValueError, KeyError, TypeError):
        return res
    text = " ".join(" ".join(i["reasons"] + i["cautions"]) for i in items)
    res["V2_exists"] = all(i["product_id"] in allowed_ids for i in items)
    res["V3_numbers"] = _numbers(text) <= allowed_numbers
    res["V5_banned"] = not any(b in text for b in BANNED)
    res["V6_required"] = all(p in text for p in required_phrases)
    return res


def generate(db: Database, application_id: str | None, use_case: str, facts: dict, *, allowed_numbers: set[str],
             allowed_ids: set[str], required_phrases: list[str], fallback: dict) -> LlmResult:
    """게이트웨이 1회 호출. 검증을 하나라도 통과하지 못하면 고정 템플릿(fallback)을 쓴다."""
    started = time.monotonic()
    masked_facts = json.loads(mask_pii(dumps(facts)))            # 개인정보 패턴 제거 후 전달
    provider = _provider()
    used_fallback, output = False, fallback
    try:
        text = provider.complete(use_case, masked_facts)
        res = validate(text, allowed_numbers, allowed_ids, required_phrases)
        if all(res.values()):
            output = json.loads(text)
        else:
            used_fallback = True
    except GuardrailViolation:
        res, used_fallback = {"provider": "unavailable"}, True
    call_id = new_id("llm")
    db.insert("llm_call_log", {"call_id": call_id, "application_id": application_id, "use_case_id": use_case,
                               "prompt_version": 1, "model_tier": "standard", "provider": provider.name,
                               "input_hash": sha256(dumps(masked_facts)), "output_masked": mask_pii(dumps(output)),
                               "validation": res, "fallback_used": int(used_fallback),
                               "latency_ms": int((time.monotonic() - started) * 1000), "created_at": now_iso()})
    return LlmResult(output, used_fallback, res, call_id)
