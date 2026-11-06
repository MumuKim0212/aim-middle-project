"""대출 API(docs/loan 기획서). 로그인 필요 API 는 전부 `Depends(current_user)` 로 보호하고, user 는 세션에서만 얻는다(공통.md 3장).

  GET  /api/loans/products                       상품 목록          GET  /api/loans                         내 대출 목록
  GET  /api/loans/{no}  /schedule  /prepay-quote  대출 상세·상환 일정·중도상환 견적
  POST /api/loans/{no}/prepay|withdraw           중도상환(간편비밀번호 재확인 + Idempotency-Key)·청약철회(간편비밀번호 재확인)
  POST /api/loans/{no}/rate-cut|extend|certificates   금리인하요구·기간연장·증명서
  POST /api/loans/applications                   신청 시작(상품, 체험 고객 선택)    GET  /api/loans/applications/{id}   진행 상태
  POST /api/loans/applications/{id}/<단계>        precheck, consents, existing, targets, profile, policy-check,
                                                 guarantee, affiliation, docs, review, choose, compare, terms, price,
                                                 explain, contract, collateral, execute(간편비밀번호 재확인 + Idempotency-Key)

신청 진행 상태(Session)는 서버 메모리에 둔다. shortcut: 서버를 다시 켜거나 30분 지나면 진행 중 신청이 사라져 처음부터 다시 해야 한다(확정된 단계는 DB 에 남는다), 여러 서버로 늘릴 때 DB 에서 복원하도록 바꾼다.
증빙 파일 업로드는 아직 없다(서버 경로를 받지 않는다). 체험 고객 샘플·공공 자동 연동만 쓸 수 있다.
"""
from __future__ import annotations

import re
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import models as m
from ..auth.deps import current_user, require_pin_verified, validation_error
from ..db import get_db
from . import management as M
from .application import Session, product_row, products
from .database import Database
from .errors import InvalidTransition, NotFound, SagaFailed
from .security import RATE_LIMITER

router = APIRouter(prefix="/api/loans", tags=["loans"])

SESSION_TTL = 30 * 60
_SESSIONS: dict[str, dict] = {}  # application_id → {"s": Session, "t": 마지막 사용 시각, "cands": 추천 후보}
Won = Annotated[int, Field(strict=True)]
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=36)]


def _camel(x: Any) -> Any:
    if isinstance(x, dict):
        return {re.sub(r"_([a-z0-9])", lambda g: g.group(1).upper(), str(k)): _camel(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_camel(v) for v in x]
    return x


def out(x: Any) -> Any:
    """Decimal·date·dataclass 를 JSON 으로, 키는 camelCase 로(공통.md 6장)."""
    return _camel(jsonable_encoder(x))


def _entry(dbs: DbSession, user: m.User, app_id: str) -> dict:
    """내 신청만 찾는다. 없는 신청·남의 신청·만료된 신청은 똑같이 404 다."""
    now = time.time()
    for k in [k for k, e in _SESSIONS.items() if now - e["t"] > SESSION_TTL]:
        del _SESSIONS[k]
    e = _SESSIONS.get(app_id)
    if e is None or e["s"].user_id != user.id:
        raise NotFound("신청을 찾을 수 없습니다. 만료되었다면 처음부터 다시 신청해 주세요.")
    e["t"] = now
    e["s"].db = Database(dbs)  # 요청마다 DB 세션이 달라지므로 다시 묶는다
    return e


def _need(s: Session, *attrs: str) -> None:
    """앞 단계가 끝나 메모리에 채워졌는지 확인한다. 순서를 건너뛴 요청은 409 가 되고, 서버 오류(500)가 되지 않는다."""
    if not all(getattr(s, a) for a in attrs):
        raise InvalidTransition()


def _public(acc: dict) -> dict:
    """대출 계좌 행에서 화면에 보낼 필요 없는 내부 값(계좌번호 해시, 회원 번호)을 뺀다."""
    return {k: v for k, v in acc.items() if k not in ("account_hash", "user_id")}


def _app_state(s: Session) -> dict:
    return {"applicationId": s.app_id, "status": s.status(), "flow": s.flow, "productId": s.product["product_id"], "contractNo": s.contract}


# ───────────── 상품·내 대출 ─────────────

@router.get("/products")
def list_products(dbs: DbSession = Depends(get_db)):
    """상품 안내(로그인 없이)."""
    return out({"items": products(Database(dbs))})


@router.get("")
def my_loans(user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    return out({"items": [_public(a) for a in M.accounts(Database(dbs), user.id)]})


class StartIn(BaseModel):
    productId: str = Field(max_length=20)
    scenarioKey: str | None = Field(default=None, max_length=20)


@router.post("/applications", status_code=201)
def start_application(body: StartIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    db = Database(dbs)
    s = Session.start(db, body.productId, body.scenarioKey, channel="WEB", user_id=user.id)
    dbs.commit()
    _SESSIONS[s.app_id] = {"s": s, "t": time.time(), "cands": []}
    return out({**_app_state(s), "product": s.product})


@router.get("/applications/{app_id}")
def get_application(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s = _entry(dbs, user, app_id)["s"]
    return out({**_app_state(s), "terms": s.terms or None, "finalRate": s.final_rate})


class PrecheckIn(BaseModel):
    homeless: bool
    married: bool
    householdIncome: Won
    netAssets: Won


class ConsentsIn(BaseModel):
    agreed: dict[str, bool]


class TargetsIn(BaseModel):
    indexes: list[int] | None = None


class ProfileIn(BaseModel):
    job: str | None = None
    income: Won | None = None
    tenure: Won | None = None
    debtMonthly: Won | None = None
    amount: Won | None = None
    term: Won | None = None
    repay: str | None = None
    ratePref: str | None = None
    delinq1y: bool | None = None
    ackUnsuitable: bool = False


class GuaranteeIn(BaseModel):
    agency: str | None = None


class AffiliationIn(BaseModel):
    orgId: str
    empNo: str
    empType: str


class DocsIn(BaseModel):
    autoLink: bool = False


class ChooseIn(BaseModel):
    variant: str


class CompareIn(BaseModel):
    confirmUnfavorable: bool = False


class TermsIn(BaseModel):
    amount: Won | None = None
    term: Won | None = None
    repay: str | None = None
    paymentDay: Won = 25
    debitAccountId: Won | None = None


class PriceIn(BaseModel):
    prefs: list[str] | None = None


class ExplainIn(BaseModel):
    scrolled: bool
    answers: list[str]


class ContractIn(BaseModel):
    confirmations: list[bool]


class ExecuteIn(BaseModel):
    accountId: Won | None = None


def _step(dbs: DbSession, user: m.User, app_id: str) -> tuple[Session, dict]:
    e = _entry(dbs, user, app_id)
    return e["s"], e


@router.post("/applications/{app_id}/precheck")
def precheck(app_id: str, body: PrecheckIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    res = s.precheck(body.homeless, body.married, body.householdIncome, body.netAssets)
    dbs.commit()
    return out({"items": [{"name": n, "ok": ok, "code": None if ok else c} for n, ok, c in res], **_app_state(s)})


@router.get("/applications/{app_id}/consents")
def required_consents(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    rows = Database(dbs).all("SELECT code, title, required_for FROM consent_code")
    names = {r["code"]: r for r in rows}
    return out({"required": [{"code": c, "title": names[c]["title"]} for c in s.required_consents()]})


@router.post("/applications/{app_id}/consents")
def give_consents(app_id: str, body: ConsentsIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    s.give_consents(body.agreed)
    dbs.commit()
    return out(_app_state(s))


@router.post("/applications/{app_id}/existing")
def fetch_existing(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    """대환: 기존 대출 조회(마이데이터 동의 필요)."""
    s, _ = _step(dbs, user, app_id)
    RATE_LIMITER.check(f"user:{user.id}:mydata")
    items = s.fetch_existing()
    dbs.commit()
    return out({"items": items, **_app_state(s)})


@router.post("/applications/{app_id}/targets")
def select_targets(app_id: str, body: TargetsIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    items = s.select_targets(body.indexes)
    dbs.commit()
    return out({"items": items, **_app_state(s)})


@router.post("/applications/{app_id}/profile")
def submit_profile(app_id: str, body: ProfileIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    form = {k: v for k, v in {"job": body.job, "income": body.income, "tenure": body.tenure, "debt_monthly": body.debtMonthly,
                              "amount": body.amount, "term": body.term, "repay": body.repay, "rate_pref": body.ratePref,
                              "delinq_1y": body.delinq1y}.items() if v is not None}
    result, burden, plan = s.submit_profile(form, ack_unsuitable=body.ackUnsuitable)
    dbs.commit()
    return out({"suitability": result, "burdenRatio": burden, "adjustPlan": plan, **_app_state(s)})


@router.post("/applications/{app_id}/policy-check")
def policy_check(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    ok = s.policy_check()
    dbs.commit()
    return out({"passed": ok, **_app_state(s)})


@router.get("/applications/{app_id}/guarantee-options")
def guarantee_options(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    _need(s, 'applicant')
    return out({"items": s.guarantee_options()})


@router.post("/applications/{app_id}/guarantee")
def choose_guarantee(app_id: str, body: GuaranteeIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    _need(s, 'applicant')
    ok = s.choose_guarantee(body.agency)
    dbs.commit()
    return out({"approved": ok, "agency": s.agency, **_app_state(s)})


@router.post("/applications/{app_id}/affiliation")
def affiliation(app_id: str, body: AffiliationIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    ok = s.affiliation(body.orgId, body.empNo, body.empType)
    dbs.commit()
    return out({"passed": ok, **_app_state(s)})


@router.get("/applications/{app_id}/docs")
def required_docs(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    return out({"items": s.docs()})


@router.post("/applications/{app_id}/docs")
def submit_docs(app_id: str, body: DocsIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    defects = s.submit_docs(auto_link=body.autoLink)  # files 는 넘기지 않는다: 서버 경로를 받지 않는다
    dbs.commit()
    return out({"defects": defects, **_app_state(s)})


@router.post("/applications/{app_id}/review")
def run_review(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, e = _step(dbs, user, app_id)
    RATE_LIMITER.check(f"user:{user.id}:review")
    r = s.run_review()
    e["cands"] = []
    dbs.commit()
    return out({"result": r.result, "limit": r.limit, "rate": r.rate, "dsr": r.dsr, "hardCodes": r.hard, "conditionCodes": r.cond,
                "docCodes": r.docs, "stages": [{"name": n, "mark": k, "text": t} for n, k, t in r.stages], **_app_state(s)})


@router.get("/applications/{app_id}/recommendations")
def recommendations(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, e = _step(dbs, user, app_id)
    _need(s, 'applicant', 'review')
    e["cands"] = s.recommend()
    dbs.commit()
    return out({"items": e["cands"]})


@router.post("/applications/{app_id}/choose")
def choose(app_id: str, body: ChooseIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, e = _step(dbs, user, app_id)
    cand = next((c for c in e["cands"] if c["variant"] == body.variant), None)
    if cand is None:
        raise NotFound("추천 후보를 찾을 수 없습니다. 추천을 다시 조회해 주세요.")
    s.choose(cand)
    dbs.commit()
    return out({"variant": body.variant, "rate": cand["rate"]})


@router.post("/applications/{app_id}/compare")
def compare(app_id: str, body: CompareIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    """대환: 갈아타기 이득 비교."""
    s, _ = _step(dbs, user, app_id)
    _need(s, 'applicant', 'review', 'targets')
    res = s.compare(body.confirmUnfavorable)
    dbs.commit()
    return out(res)


@router.post("/applications/{app_id}/terms")
def set_terms(app_id: str, body: TermsIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    _need(s, 'applicant', 'review')
    terms = s.set_terms(body.amount, body.term, body.repay, body.paymentDay, body.debitAccountId)
    dbs.commit()
    return out({"terms": terms, **_app_state(s)})


@router.post("/applications/{app_id}/price")
def price(app_id: str, body: PriceIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    _need(s, 'review')
    final = s.price(body.prefs)
    dbs.commit()
    return out({"finalRate": final, "monthly": s.monthly(), **_app_state(s)})


@router.get("/applications/{app_id}/quiz")
def quiz(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    return out({"items": [q for q, _ in s.quiz()]})  # 정답은 내려주지 않는다


@router.post("/applications/{app_id}/explain")
def explain(app_id: str, body: ExplainIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    s.explain(body.scrolled, body.answers)
    dbs.commit()
    return out(_app_state(s))


@router.post("/applications/{app_id}/contract")
def sign_contract(app_id: str, body: ContractIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    _need(s, 'terms', 'final_rate')
    cno = s.sign_contract(body.confirmations)
    dbs.commit()
    return out({"contractNo": cno, **_app_state(s)})


@router.post("/applications/{app_id}/collateral")
def set_collateral(app_id: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    s, _ = _step(dbs, user, app_id)
    _need(s, 'contract')
    s.set_collateral()
    dbs.commit()
    return out(_app_state(s))


@router.post("/applications/{app_id}/execute")
def execute(app_id: str, body: ExecuteIn, request: Request, idem: IdemKey, user: m.User = Depends(current_user),
            dbs: DbSession = Depends(get_db)):
    """대출 실행. 본인 지급(신용·예금담보)은 accountId 의 내 저축예금에 입금한다(같은 트랜잭션)."""
    s, _ = _step(dbs, user, app_id)
    _need(s, 'contract')
    require_pin_verified(request)
    if s.product["collateral_type"] in ("CREDIT", "DEPOSIT") and not s.refi and body.accountId is None:
        raise validation_error("accountId", "REQUIRED", "대출금을 받을 계좌를 선택해 주세요.")
    try:
        cno = s.execute(f"u{user.id}:{idem}", account_id=body.accountId)  # 키는 회원별로 나눈다
    except SagaFailed:
        dbs.commit()  # 실패 상태(REFI_FAILED)와 보상 기록은 남긴다
        raise
    dbs.commit()
    _SESSIONS.pop(app_id, None)
    return out({"contractNo": cno, "status": "COMPLETED"})


# ───────────── 내 대출 관리 ─────────────

def _mine(dbs: DbSession, user: m.User, no: str) -> tuple[Database, dict]:
    db = Database(dbs)
    return db, M.account(db, no, user.id)


class PrepayIn(BaseModel):
    principal: Won
    accountId: Won | None = None


class RateCutIn(BaseModel):
    reasons: list[str]


class ExtendIn(BaseModel):
    months: Won


class CertIn(BaseModel):
    type: str


@router.get("/{no}")
def loan_detail(no: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    _, acc = _mine(dbs, user, no)
    return out(_public(acc))


@router.get("/{no}/schedule")
def loan_schedule(no: str, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    _, acc = _mine(dbs, user, no)
    return out(M.full_schedule(acc))


@router.get("/{no}/prepay-quote")
def prepay_quote(no: str, principal: int = Query(ge=1), user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    _, acc = _mine(dbs, user, no)
    return out(M.prepay_quote(acc, principal))


@router.post("/{no}/prepay")
def prepay(no: str, body: PrepayIn, request: Request, idem: IdemKey, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    db, _ = _mine(dbs, user, no)
    require_pin_verified(request)
    res = M.prepay(db, no, body.principal, f"u{user.id}:{idem}", body.accountId)
    dbs.commit()
    return out(res)


@router.post("/{no}/withdraw")
def withdraw(no: str, request: Request, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    db, _ = _mine(dbs, user, no)
    require_pin_verified(request)
    res = M.withdraw(db, no)
    dbs.commit()
    return out(res)


@router.post("/{no}/rate-cut")
def rate_cut(no: str, body: RateCutIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    db, _ = _mine(dbs, user, no)
    res = M.rate_cut(db, no, body.reasons)
    dbs.commit()
    return out(res)


@router.post("/{no}/extend")
def extend(no: str, body: ExtendIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    db, _ = _mine(dbs, user, no)
    res = M.extend(db, no, body.months)
    dbs.commit()
    return out(res)


@router.post("/{no}/certificates", status_code=201)
def certificate(no: str, body: CertIn, user: m.User = Depends(current_user), dbs: DbSession = Depends(get_db)):
    db, _ = _mine(dbs, user, no)
    cert = M.certificate(db, no, body.type)
    dbs.commit()
    return out({"certNo": cert})
