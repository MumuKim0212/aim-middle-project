"""[역할] 동의 관리와 동의 게이트(main 5.1): 필요한 동의가 없으면 외부 조회를 아예 실행하지 않는다."""
from __future__ import annotations

from .database import Database, now_iso
from .errors import ConsentMissing
from .ids import new_id
from .security import RATE_LIMITER, sha256

# 조회 출처별 필요 동의 (main 5.3 표)
SOURCE_CONSENTS = {
    "CB": ["CREDIT_INQUIRY"],
    "PUBLIC": ["PUBLIC_SCRAPING"],
    "ADMIN": ["ADMIN_INFO"],
    "MYDATA": ["MYDATA_TRANSFER"],
    "GUARANTOR": ["GUARANTOR_PROVIDE"],
    "ORG": ["ORG_EMPLOYMENT"],
    "AGENCY": ["AGENCY_PROVIDE"],
    "REFI_INFRA": ["PAYOFF_PROVIDE"],
    "PRICE": [], "REGISTRY": [],
}


def required_codes(business_type: str, inst_kind: str | None, married: bool = False) -> list[str]:
    """업무별 필수 동의 코드 목록."""
    req = ["TERMS_BASIC", "COLLECT_USE", "UNIQUE_ID", "CREDIT_INQUIRY", "PROVIDE_3RD"]
    if business_type == "POLICY":
        req += ["ADMIN_INFO", "AGENCY_PROVIDE"] + (["SPOUSE_INQUIRY"] if married else [])
    if business_type == "INST":
        req += ["GUARANTOR_PROVIDE"] if inst_kind == "A" else ["ORG_EMPLOYMENT"]
    if business_type == "REFI":
        req += ["MYDATA_TRANSFER", "PAYOFF_PROVIDE"]
    return req


def record(db: Database, application_id: str, code: str, agreed: bool, auth_ref: str | None = None) -> None:
    """동의 1건 기록(문서 버전 해시를 함께 고정)."""
    row = db.one("SELECT f.version_hash FROM consent_code c LEFT JOIN form_template f ON f.form_no = c.form_no WHERE c.code = ?", (code,))
    if row is None:
        raise ConsentMissing(detail=f"unknown consent {code}")
    db.insert("consent_record", {"consent_id": new_id("cns"), "application_id": application_id, "consent_code": code,
                                 "agreed": int(agreed), "doc_version_hash": row["version_hash"] or "",
                                 "auth_ref": auth_ref, "agreed_at": now_iso(), "withdrawn_at": None})


def agreed_codes(db: Database, application_id: str) -> set[str]:
    """각 코드의 가장 최근 기록 기준으로, 동의했고 철회하지 않은 코드."""
    rows = db.all("""SELECT consent_code, agreed, withdrawn_at FROM consent_record c1
                     WHERE application_id = ? AND consent_id = (SELECT MAX(consent_id) FROM consent_record c2
                       WHERE c2.application_id = c1.application_id AND c2.consent_code = c1.consent_code)""", (application_id,))
    # consent_id는 ULID라 사전순 = 기록 순서 → 코드마다 가장 마지막 기록만 본다
    return {r["consent_code"] for r in rows if r["agreed"] and not r["withdrawn_at"]}


def missing(db: Database, application_id: str, codes: list[str]) -> list[str]:
    have = agreed_codes(db, application_id)
    return [c for c in codes if c not in have]


def gate(db: Database, application_id: str, source: str, purpose: str, rate_key: str) -> str:
    """동의 게이트 + 속도 제한. 통과하면 조회 1건용 토큰(해시)을 돌려주고 조회 기록을 남긴다."""
    need = SOURCE_CONSENTS.get(source)
    if need is None:
        raise ConsentMissing(detail=f"unknown source {source}")
    lacking = missing(db, application_id, need)
    status = "BLOCKED" if lacking else "OK"
    token = sha256(f"{application_id}|{source}|{purpose}|{now_iso()}")
    db.insert("inquiry_log", {"inquiry_id": new_id("inq"), "application_id": application_id, "source": source,
                              "purpose": purpose, "consent_codes": need, "request_hash": token,
                              "response_hash": None, "status": status, "fetched_at": now_iso()})
    if lacking:
        raise ConsentMissing(f"필요한 동의({', '.join(lacking)})가 없어 {source} 조회를 하지 않았습니다.", detail=source)
    RATE_LIMITER.check(f"{rate_key}:{source}")
    return token
