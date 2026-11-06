"""[역할] 신청서 상태 전이 규칙(main 3장): 허용되지 않은 단계 이동을 차단하고 이력을 남긴다."""
from __future__ import annotations

from .database import Database, now_iso
from .errors import InvalidTransition
from .ids import new_id

ALLOWED: dict[str, set[str]] = {
    "DRAFT": {"POLICY_CHECKING", "CONSENTED", "CANCELLED", "EXPIRED"},
    "POLICY_CHECKING": {"CONSENTED", "POLICY_INELIGIBLE", "CANCELLED"},
    "CONSENTED": {"LOANS_FETCHED", "PROFILED", "UNSUITABLE", "CANCELLED", "EXPIRED"},
    "LOANS_FETCHED": {"TARGET_SELECTED", "REFI_INELIGIBLE", "CANCELLED"},
    "TARGET_SELECTED": {"PROFILED", "UNSUITABLE", "CANCELLED"},
    "UNSUITABLE": {"PROFILED", "CANCELLED"},
    "PROFILED": {"POLICY_INELIGIBLE", "AFFILIATION_FAILED", "GUARANTEE_REJECTED", "DOCS_SUBMITTED", "PROFILED", "CANCELLED", "EXPIRED"},
    "DOCS_SUBMITTED": {"UNDER_REVIEW", "CANCELLED"},
    "UNDER_REVIEW": {"APPROVED", "COND_APPROVED", "DOCS_REQUIRED", "REJECTED"},
    "DOCS_REQUIRED": {"DOCS_SUBMITTED", "EXPIRED", "CANCELLED"},
    "APPROVED": {"TERMS_SET", "CANCELLED", "EXPIRED"},
    "COND_APPROVED": {"TERMS_SET", "CANCELLED", "EXPIRED"},
    "TERMS_SET": {"PRICED", "TERMS_SET", "CANCELLED"},
    "PRICED": {"EXPLAINED", "TERMS_SET", "CANCELLED"},
    "EXPLAINED": {"CONTRACTED", "CANCELLED"},
    "CONTRACTED": {"COLLATERAL_SET", "DISBURSED", "REFI_FAILED"},
    "COLLATERAL_SET": {"DISBURSED", "REFI_FAILED"},
    "DISBURSED": {"PAID_OFF", "COMPLETED", "REFI_FAILED"},
    "PAID_OFF": {"COMPLETED"},
    "COMPLETED": set(),                       # 청약철회는 대출 계좌 상태에서 처리 (대출관리 M07)
    "REJECTED": set(), "CANCELLED": set(), "EXPIRED": set(), "POLICY_INELIGIBLE": set(),
    "AFFILIATION_FAILED": set(), "GUARANTEE_REJECTED": set(), "REFI_INELIGIBLE": set(), "REFI_FAILED": set(),
}
TERMINAL = {k for k, v in ALLOWED.items() if not v}


def transition(db: Database, application_id: str, to_status: str, step: str, actor: str = "system") -> None:
    """현재 상태에서 to_status로 갈 수 있을 때만 바꾸고 이력·감사 로그를 남긴다."""
    row = db.one("SELECT status FROM loan_application WHERE application_id = ?", (application_id,))
    if row is None:
        raise InvalidTransition(detail="no application")
    cur = row["status"]
    if to_status not in ALLOWED.get(cur, set()):
        raise InvalidTransition(f"지금 단계({cur})에서는 {to_status}(으)로 진행할 수 없습니다.", detail=f"{cur}->{to_status}")
    ts = now_iso()
    db.update("loan_application", {"application_id": application_id}, {"status": to_status, "updated_at": ts})
    db.insert("application_status_history", {"history_id": new_id("hst"), "application_id": application_id,
                                             "from_status": cur, "to_status": to_status, "step_code": step,
                                             "actor": actor, "created_at": ts})
    db.audit("loan_application", application_id, f"STATUS:{cur}->{to_status}", {"step": step}, actor)
