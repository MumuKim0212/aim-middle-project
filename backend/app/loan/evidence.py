"""[역할] 증빙 처리(main 5.4): 필요 서류 목록, 파일 검사(확장자·크기·파일 시그니처·해시), 결함 코드 판정."""
from __future__ import annotations

from pathlib import Path

from . import config
from .database import Database, now_iso
from .errors import ValidationError
from .ids import new_id
from .security import sha256


def required_docs(product, job: str) -> list[dict]:
    """구현명세 14.2와 같은 서류 목록(키·이름·필수·자동연동·체험 파일명)."""
    cat, btype, kind = product["collateral_type"], product["business_type"], product["inst_kind"]
    refi, biz = btype == "REFI", job == "개인사업자"
    d: list[dict] = []
    if cat != "DEPOSIT":
        d.append({"key": "income", "name": "소득금액증명원" if biz else "근로소득 원천징수영수증", "req": True, "auto": True,
                  "sample": "공통_소득증빙_소득금액증명원.pdf" if biz else "공통_소득증빙_근로소득 원천징수영수증.pdf"})
        if not (btype == "INST" and kind == "B"):
            d.append({"key": "emp", "name": "사업자등록증명" if biz else "재직증명서", "req": True, "auto": True,
                      "sample": "공통_사업증빙_사업자등록증명.pdf" if biz else "공통_재직증빙_재직증명서.pdf"})
        d.append({"key": "hi", "name": "건강보험 자격득실확인서", "req": False, "auto": True, "sample": "공통_재직증빙_건강보험 자격득실확인서.pdf"})
    if cat == "JEONSE":
        d.append({"key": "lease", "name": "임대차계약서 (현재 주택)" if refi else "임대차계약서 (확정일자 포함)", "req": True, "auto": False,
                  "sample": "대환_담보_주택 임대차계약서(현재 주택).pdf" if refi else "대출_담보_주택 임대차계약서(신규 주택).pdf"})
        d.append({"key": "reg", "name": "등기사항전부증명서", "req": not refi, "auto": False, "sample": "대출_담보_등기사항전부증명서(신규 주택).pdf"})
    if cat == "MORTGAGE":
        if refi:
            d.append({"key": "reg", "name": "등기사항전부증명서 (보유 주택)", "req": True, "auto": False, "sample": "대환_담보_등기사항전부증명서(보유 주택).pdf"})
        else:
            d.append({"key": "sale", "name": "부동산 매매계약서", "req": True, "auto": False, "sample": "대출_담보_부동산 매매계약서.pdf"})
            d.append({"key": "reg", "name": "등기사항전부증명서", "req": True, "auto": False, "sample": "대출_담보_등기사항전부증명서(구입 주택).pdf"})
    if cat == "AUTO":
        d.append({"key": "car", "name": "자동차등록원부" if refi else "자동차 매매계약서·견적서", "req": True, "auto": False,
                  "sample": "대환_담보_자동차등록원부(기존 차량).pdf" if refi else "대출_담보_자동차 매매계약서.pdf"})
    if btype == "POLICY":
        d.append({"key": "family", "name": "가족관계증명서", "req": False, "auto": True, "sample": "(행정정보 연동)"})
    if refi:
        d.append({"key": "bal", "name": "기존 대출 잔액증명서", "req": False, "auto": False, "sample": "대환_기존대출_대출 잔액증명서.pdf"})
    return d


def inspect_file(path: str | Path) -> dict:
    """업로드 파일 검사: 확장자 허용 목록, 10MB 이하, 파일 앞부분 시그니처가 확장자와 맞는지(위장 파일 차단)."""
    p = Path(path)
    if not p.is_file():
        raise ValidationError("파일을 찾을 수 없습니다.")
    ext = p.suffix.lower()
    size = p.stat().st_size
    if ext not in config.ALLOWED_EXT or size > config.MAX_FILE_BYTES or size == 0:
        return {"ok": False, "name": p.name, "size": size, "sha256": None, "reason": "DOC-INVALID"}
    with p.open("rb") as fh:
        head = fh.read(8)
    if not head.startswith(config.MAGIC[ext]):
        return {"ok": False, "name": p.name, "size": size, "sha256": None, "reason": "DOC-INVALID"}
    return {"ok": True, "name": p.name, "size": size, "sha256": sha256(p.read_bytes()), "reason": None}


def save(db: Database, application_id: str, doc: dict, source: str, info: dict | None, defects: list[str]) -> None:
    db.insert("evidence", {"evidence_id": new_id("evd"), "application_id": application_id, "doc_key": doc["key"],
                           "doc_type": doc["name"], "source": source, "file_name": (info or {}).get("name"),
                           "file_size": (info or {}).get("size"), "file_sha256": (info or {}).get("sha256"),
                           "extracted": {}, "confidence": {}, "defect_codes": defects,
                           "status": "OK" if not defects else ("INVALID" if "DOC-INVALID" in defects else "DEFECT"),
                           "created_at": now_iso()})


def judge(docs: list[dict], attached: dict[str, dict], scenario_defects: list[str], refi_doc_expired: bool) -> list[str]:
    """결함 코드: 필수 미제출 DOC-MISSING, 형식 오류 DOC-INVALID, 체험 고객 결함, 대환 잔액증명서 경과 DOC-EXPIRED."""
    out: list[str] = []
    for d in docs:
        a = attached.get(d["key"])
        if d["req"] and not a:
            out.append("DOC-MISSING")
        if a and not a.get("ok", True):
            out.append("DOC-INVALID")
    out += scenario_defects
    if refi_doc_expired:
        out.append("DOC-EXPIRED")
    return list(dict.fromkeys(out))
