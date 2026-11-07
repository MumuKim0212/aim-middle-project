"""[역할] 신청 오케스트레이터: 업무별 단계(C01~C14, G/I/R 확장)를 상태 머신·동의 게이트·검증과 함께 순서대로 실행한다."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D

from sqlalchemy import and_, case, func, select

from .. import models as m
from . import catalog as C
from . import config as K
from . import consent, evidence, recommendation, refinance
from .calculators import add_months, monthly_payment, schedule, to_won
from .database import Database, now_iso
from .errors import ConsentMissing, DuplicateRequest, InvalidTransition, LimitExceeded, NotFound, SagaFailed, ValidationError
from .ids import contract_no, loan_account_no, new_id
from .security import keyed_hash, mask_account, sha256
from .state_machine import TERMINAL, transition
from .underwriting import Applicant, Review, adjust_plan, est_rate, review, suitability
from .validation import JOBS, RATE_PREFS, choice, desired_amount, employee_no, int_range
from ..accounts import service as account_service


def product_row(db: Database, pid: str) -> dict:
    """상품 1건(JSON 컬럼 풀어서)."""
    r = db.one("SELECT * FROM product_catalog WHERE product_id = ?", (pid,))
    if r is None:
        raise NotFound("상품을 찾을 수 없습니다.")
    p = dict(r)
    p["term_options"], p["repay_options"] = json.loads(p["term_options"]), json.loads(p["repay_options"])
    return p


def products(db: Database, refi: bool | None = None) -> list[dict]:
    rows = db.all("SELECT product_id FROM product_catalog ORDER BY sort_no")
    ps = [product_row(db, r["product_id"]) for r in rows]
    if refi is None:
        return ps
    return [p for p in ps if (p["business_type"] == "REFI") == refi]


FLOW = {
    "GENERAL": ["consent", "profile", "docs", "review", "result", "terms", "pricing", "explain", "contract", "collateral", "execute", "done"],
    "POLICY": ["precheck", "consent", "profile", "policycheck", "docs", "review", "result", "terms", "pricing", "explain", "contract", "collateral", "execute", "done"],
    "INST_A": ["consent", "profile", "guarantee", "docs", "review", "result", "terms", "pricing", "explain", "contract", "collateral", "execute", "done"],
    "INST_B": ["consent", "profile", "affiliation", "docs", "review", "result", "terms", "pricing", "explain", "contract", "execute", "done"],
    "REFI": ["consent", "fetch", "targets", "profile", "docs", "review", "compare", "terms", "pricing", "explain", "contract", "collateral", "execute", "payoff", "done"],
}
QUIZ = [("변동금리는 시장 금리가 오르면 월 상환액이 늘어날 수 있다.", "O"),
        ("계약서류를 받은 날(또는 실행일)부터 14일 안에는 청약철회를 할 수 있다.", "O")]


@dataclass
class Session:
    """신청 1건의 진행 상태(메모리). 확정된 값은 단계마다 DB에 저장된다."""
    db: Database
    app_id: str
    product: dict
    scenario: dict | None
    applicant: Applicant | None = None
    married: bool = False
    targets: list = field(default_factory=list)
    existing: list = field(default_factory=list)
    defects: list = field(default_factory=list)
    review: object = None
    chosen_rate: D | None = None
    final_rate: D | None = None
    terms: dict = field(default_factory=dict)
    refi_result: dict | None = None
    suit_override: bool = False
    contract: str | None = None
    account_no: str | None = None
    agency: str | None = None
    user_id: int | None = None  # 서버에서는 세션의 회원 번호. 콘솔·시험에서는 None
    cands: list = field(default_factory=list)  # 추천 후보(추천 조회 때 채우고, 선택 때 읽는다)
    pref_result: dict = field(default_factory=dict)  # 마지막 금리 확정의 우대 적용·불가({"applied": [...], "denied": [...]}), 저장하지 않는다

    # ------------------------------------------------------------------ 공통
    @property
    def flow_key(self) -> str:
        p = self.product
        return f"INST_{p['inst_kind']}" if p["business_type"] == "INST" else p["business_type"]

    @property
    def flow(self) -> list[str]:
        steps = list(FLOW[self.flow_key])
        if self.product["collateral_type"] == "CREDIT" and "collateral" in steps and self.flow_key in ("GENERAL", "REFI"):
            steps.remove("collateral")
        return steps

    @property
    def refi(self) -> bool:
        return self.product["business_type"] == "REFI"

    def status(self) -> str:
        return self.db.one("SELECT status FROM loan_application WHERE application_id = ?", (self.app_id,))["status"]

    def excluded_monthly(self) -> int:
        return sum(t["monthly"] for t in self.targets) if self.refi else 0

    # ------------------------------------------------------------------ 진행 상태 보관·복원
    def snapshot(self) -> dict:
        """메모리에만 있는 진행 상태를 JSON 으로 만든다(loan_application.session_state 에 저장, Decimal 은 문자열이 된다).
        shortcut: 대환 유불리(refi_result)는 담지 않는다. 어디서도 읽지 않는다."""
        return {"married": self.married, "targets": self.targets, "existing": self.existing, "defects": self.defects,
                "applicant": asdict(self.applicant) if self.applicant else None, "review": asdict(self.review) if self.review else None,
                "chosen_rate": self.chosen_rate, "final_rate": self.final_rate, "terms": self.terms,
                "suit_override": self.suit_override, "contract": self.contract, "agency": self.agency, "cands": self.cands}

    @classmethod
    def restore(cls, db: Database, app_id: str, user_id: int) -> "Session | None":
        """메모리에 없는 내 미완료 신청의 진행 상태를 DB 에서 되살린다(없거나 남의 것이거나 끝났거나 만료됐으면 None)."""
        r = db.one("SELECT product_id, scenario_key, status, session_state FROM loan_application "
                   "WHERE application_id = ? AND user_id = ? AND expires_at > now()", (app_id, user_id))
        if r is None or r["status"] in TERMINAL:
            return None
        st = json.loads(r["session_state"]) if r["session_state"] else {}
        rv, rate = st.get("review"), lambda k: D(st[k]) if st.get(k) is not None else None
        return cls(db, app_id, product_row(db, r["product_id"]), C.SCENARIOS.get(r["scenario_key"]), user_id=user_id,
                   applicant=Applicant(**st["applicant"]) if st.get("applicant") else None,
                   review=Review(**{**rv, "rate": D(rv["rate"]), "dsr": D(rv["dsr"])}) if rv else None,
                   chosen_rate=rate("chosen_rate"), final_rate=rate("final_rate"), married=st.get("married", False),
                   targets=st.get("targets", []), existing=st.get("existing", []), defects=st.get("defects", []),
                   terms=st.get("terms", {}), suit_override=st.get("suit_override", False), contract=st.get("contract"), agency=st.get("agency"),
                   cands=[{**c, **{k: D(c[k]) for k in ("rate", "pref", "score")}} for c in st.get("cands", [])])  # Decimal 은 문자열로 저장됐다

    # ------------------------------------------------------------------ C01 시작
    @classmethod
    def start(cls, db: Database, product_id: str, scenario_key: str | None = None, channel: str = "CLI", user_id: int | None = None,
              auth_ref: str | None = None) -> "Session":
        p = product_row(db, product_id)
        sc = C.SCENARIOS.get(scenario_key) if scenario_key else None
        app_id, ts = new_id("lap"), now_iso()
        exp = (datetime.now(timezone.utc) + timedelta(days=K.APPLICATION_TTL_DAYS)).isoformat(timespec="seconds")
        with db.tx():
            db.insert("loan_application", {"application_id": app_id, "user_id": user_id, "auth_ref": auth_ref, "product_id": product_id,
                                           "business_type": p["business_type"], "status": "DRAFT", "channel": channel,
                                           "scenario_key": scenario_key, "created_at": ts, "updated_at": ts, "expires_at": exp})
            db.audit("loan_application", app_id, "CREATE", {"product": product_id})
        return cls(db, app_id, p, sc, user_id=user_id)

    # ------------------------------------------------------------------ G01 정책 사전 확인
    def precheck(self, homeless: bool, married: bool, hh_income: int, net_assets: int) -> list[tuple[str, bool, str]]:
        rule = C.POLICY_RULES[self.product["product_id"]]
        limit = int(D(rule["income_limit"]) * (D(rule["married_factor"]) if married else 1))
        res = [("무주택", homeless, "POL-HOME-OWNED"), ("부부합산 소득" if married else "본인 연 소득", hh_income <= limit, "POL-INCOME-OVER"),
               ("순자산", net_assets <= rule["asset_limit"], "POL-ASSET-OVER")]
        self.married = married
        with self.db.tx():
            self.db.insert("household_info", {"application_id": self.app_id, "married": int(married), "homeless": int(homeless),
                                              "household_income": hh_income, "net_assets": net_assets, "spouse_user_id": None, "spouse_consent_at": None})
            transition(self.db, self.app_id, "POLICY_CHECKING" if all(r[1] for r in res) else "POLICY_INELIGIBLE", "G01")
        return res

    # ------------------------------------------------------------------ C02 동의
    def required_consents(self) -> list[str]:
        return consent.required_codes(self.product["business_type"], self.product["inst_kind"], self.married)

    def give_consents(self, agreed: dict[str, bool], auth_ref: str | None = None) -> None:
        """필수 동의를 하나라도 거부하면 다음 단계로 갈 수 없다."""
        lacking = [c for c in self.required_consents() if not agreed.get(c)]
        with self.db.tx():
            for code, ok in agreed.items():
                consent.record(self.db, self.app_id, code, bool(ok), auth_ref)
            if lacking:
                raise ConsentMissing(f"필수 동의가 필요합니다: {', '.join(lacking)}")
            transition(self.db, self.app_id, "CONSENTED", "C02")

    # ------------------------------------------------------------------ R03·R04 대환 조회·대상
    def fetch_existing(self) -> list[dict]:
        with self.db.tx():
            consent.gate(self.db, self.app_id, "MYDATA", "기존 대출 조회", self.app_id)
            loans = self.scenario["loans"] if self.scenario else C.DEFAULT_EXISTING
            self.existing = refinance.save_existing(self.db, self.app_id, loans)
            transition(self.db, self.app_id, "LOANS_FETCHED", "C02x")
        return self.existing

    def select_targets(self, indexes: list[int] | None = None) -> list[dict]:
        ok = [e for e in self.existing if not e["codes"]]
        with self.db.tx():
            if not ok:
                transition(self.db, self.app_id, "REFI_INELIGIBLE", "C02x")
                return []
            chosen = [self.existing[i] for i in indexes] if indexes else ok
            if any(c["codes"] for c in chosen):
                raise ValidationError("대환 불가 대출은 선택할 수 없습니다.")
            self.targets = chosen
            transition(self.db, self.app_id, "TARGET_SELECTED", "C02x")
        return self.targets

    # ------------------------------------------------------------------ C03 고객정보·적합성
    def build_applicant(self, form: dict) -> Applicant:
        """화면 입력을 검증해 Applicant로 만든다(시나리오 값은 기본값)."""
        p, sc = self.product, (self.scenario or {}).get("profile", {})
        job = choice(form.get("job", sc.get("job", "급여소득자")), "직업", JOBS)
        amount = refinance.refi_amount(self.targets) if self.refi else desired_amount(
            int_range(form.get("amount", sc.get("amount", min(self.default_amount(), p["max_amount"]))), "희망 금액", 0, 10_000_000_000), p)
        term = int(form.get("term", sc.get("term", self.default_term())))
        if term not in p["term_options"]:
            raise ValidationError(f"기간은 {p['term_options']} 중에서 골라 주세요.")
        repay = choice(form.get("repay", p["repay_options"][0]), "상환 방법", p["repay_options"])
        return Applicant(job=job, tenure=int_range(form.get("tenure", sc.get("tenure", 36)), "재직 기간", 0, 600),
                         income=int_range(form.get("income", sc.get("income", 50_000_000)), "연 소득", 0, 3_000_000_000),
                         debt_monthly=int_range(form.get("debt_monthly", sc.get("debt_monthly", 0)), "기존 월 상환액", 0, 1_000_000_000),
                         delinq_1y=bool(form.get("delinq_1y", sc.get("delinq_current", False))), amount=amount, term=term, repay=repay,
                         score=int(sc.get("score", 690 if form.get("delinq_1y") else 820)), inquiries=int(sc.get("inquiries", 0)),
                         multi_debt=int(sc.get("multi_debt", 0)), delinq_current=bool(sc.get("delinq_current", False)),
                         biz_closed=bool(sc.get("biz_closed", False)), deposit=int(form.get("deposit", sc.get("deposit", 200_000_000))),
                         value=int(form.get("value", sc.get("value", 320_000_000 if p["collateral_type"] == "JEONSE" else 700_000_000))),
                         senior=int(form.get("senior", sc.get("senior", 0))), price=int(form.get("price", sc.get("price", 40_000_000 if p["collateral_type"] == "AUTO" else 700_000_000))))

    def default_amount(self) -> int:
        sc = (self.scenario or {}).get("profile", {})
        return {"CREDIT": 30_000_000, "JEONSE": int(sc.get("deposit", 200_000_000) * 0.8), "MORTGAGE": 400_000_000,
                "AUTO": 30_000_000, "DEPOSIT": 30_000_000}[self.product["collateral_type"]]

    def default_term(self) -> int:
        t = self.product["term_options"]
        if self.refi and self.targets:
            rem = max(x["remain"] for x in self.targets)
            return min(t, key=lambda v: abs(v - rem))
        return t[min(2, len(t) - 1)]

    def submit_profile(self, form: dict, ack_unsuitable: bool = False) -> tuple[str, D, dict | None]:
        """적합성 판정. 부적합이면 조정안을 돌려주고, 고객이 고지를 확인(ack)해야 진행된다."""
        a = self.build_applicant(form)
        res, burden = suitability(self.product, a, self.excluded_monthly())
        plan = adjust_plan(self.product, a, self.refi, self.excluded_monthly()) if res == "UNSUITABLE" else None
        with self.db.tx():
            self.db.execute("DELETE FROM applicant_profile WHERE application_id = ?", (self.app_id,))
            self.db.insert("applicant_profile", {"application_id": self.app_id, "job_type": a.job, "employer_name": None,
                                                 "tenure_months": a.tenure, "annual_income": a.income, "assets": 0,
                                                 "debt_monthly": a.debt_monthly, "delinquent_1y": int(a.delinq_1y),
                                                 "purpose_code": "REFI" if self.refi else self.product["collateral_type"],
                                                 "desired_amount": a.amount, "desired_term": a.term, "repay_method": a.repay,
                                                 "rate_pref": form.get("rate_pref", "고정금리") if form.get("rate_pref", "고정금리") in RATE_PREFS else "고정금리",
                                                 "collateral": {"deposit": a.deposit, "value": a.value, "senior": a.senior, "price": a.price},
                                                 "credit_score": a.score, "updated_at": now_iso()})
            self.db.insert("suitability_result", {"suitability_id": new_id("sut"), "application_id": self.app_id, "result": res,
                                                  "burden_ratio": str(burden.quantize(D("0.0001"))), "reason_codes": ["SUIT-BURDEN"] if res == "UNSUITABLE" else [],
                                                  "rule_version": "SUIT-RULE@1", "override": int(res == "UNSUITABLE" and ack_unsuitable),
                                                  "override_notice": "LN-03@1" if ack_unsuitable else None, "created_at": now_iso()})
            if res == "UNSUITABLE" and not ack_unsuitable:
                if self.status() != "UNSUITABLE":
                    transition(self.db, self.app_id, "UNSUITABLE", "C03")
            else:
                self.suit_override = res == "UNSUITABLE"
                transition(self.db, self.app_id, "PROFILED", "C03")
        self.applicant = a
        return res, burden, plan

    # ------------------------------------------------------------------ C04 업무별 확인
    def policy_check(self) -> bool:
        h = self.db.one("SELECT * FROM household_info WHERE application_id = ?", (self.app_id,))
        rule = C.POLICY_RULES[self.product["product_id"]]
        limit = int(D(rule["income_limit"]) * (D(rule["married_factor"]) if h["married"] else 1))
        items = [("HOMELESS", bool(h["homeless"])), ("INCOME", h["household_income"] <= limit), ("ASSET", h["net_assets"] <= rule["asset_limit"]), ("DUP", True)]
        with self.db.tx():
            consent.gate(self.db, self.app_id, "ADMIN", "정책 자격 검증", self.app_id)
            for code, ok in items:
                self.db.insert("policy_check_result", {"check_id": new_id("pck"), "application_id": self.app_id, "policy_id": f"POL-{self.product['product_id']}",
                                                       "policy_version": 1, "item_code": code, "item_value": "-", "result": "PASS" if ok else "FAIL",
                                                       "data_source": "ADMIN", "checked_at": now_iso()})
            passed = all(ok for _, ok in items)
            if not passed:
                transition(self.db, self.app_id, "POLICY_INELIGIBLE", "G04")
        return passed

    def guarantee_options(self) -> list[dict]:
        a, out = self.applicant, []
        r = est_rate(self.product, a.score, a.income)
        ratio = D(a.senior + a.deposit) / max(D(a.value), D(1))
        for row in self.db.all("SELECT * FROM guarantee_rule ORDER BY agency"):
            ok = ratio <= D(str(row["max_ratio"])) and a.deposit <= row["cap_amount"] * D("1.25")
            amt = int(min(D(a.deposit) * K.JEONSE_LOAN_RATIO, D(row["cap_amount"])))
            intr, fee = to_won(D(amt) * r / 100 * 2), to_won(D(amt) * D(str(row["fee_rate"])) / 100 * 2)
            out.append({"agency": row["agency"], "ok": ok, "amount": amt, "fee_rate": D(str(row["fee_rate"])), "cost": intr + fee, "interest": intr, "fee": fee})
        return sorted(out, key=lambda x: x["cost"])

    def choose_guarantee(self, agency: str | None = None) -> bool:
        opts = self.guarantee_options()
        ok = [o for o in opts if o["ok"]]
        with self.db.tx():
            if not ok:
                transition(self.db, self.app_id, "GUARANTEE_REJECTED", "I04-A")
                return False
            pick = next((o for o in ok if o["agency"] == agency), ok[0])
            consent.gate(self.db, self.app_id, "GUARANTOR", "보증 신청", self.app_id)
            self.db.insert("guarantee_request", {"guarantee_id": new_id("gua"), "application_id": self.app_id, "agency": pick["agency"],
                                                 "status": "APPROVED", "approved_amount": pick["amount"], "fee_rate": str(pick["fee_rate"]),
                                                 "cert_no": None, "reason_codes": [], "requested_at": now_iso(), "issued_at": None})
            self.agency = pick["agency"]
        return True

    def affiliation(self, org_id: str, emp_no: str, emp_type: str) -> bool:
        emp_no = employee_no(emp_no)
        choice(emp_type, "고용 형태", ("정규직", "계약직"))
        if not self.db.one("SELECT 1 FROM agreement_org WHERE org_id = ?", (org_id,)):
            raise ValidationError("협약기관을 선택하세요.")
        ok = emp_type == "정규직"
        with self.db.tx():
            consent.gate(self.db, self.app_id, "ORG", "재직 확인", self.app_id)
            self.db.insert("affiliation_check", {"affiliation_id": new_id("aff"), "application_id": self.app_id, "org_id": org_id,
                                                 "method": "ORG_API", "employee_no_hash": keyed_hash(emp_no), "employment_type": emp_type,
                                                 "result": "PASS" if ok else "FAIL", "checked_at": now_iso()})
            if not ok:
                transition(self.db, self.app_id, "AFFILIATION_FAILED", "I04-B")
        return ok

    # ------------------------------------------------------------------ C04 증빙
    def docs(self) -> list[dict]:
        return evidence.required_docs(self.product, self.applicant.job if self.applicant else "급여소득자")

    def submit_docs(self, files: dict[str, str] | None = None, auto_link: bool = False, use_demo: bool = True) -> list[str]:
        """files: {doc_key: 파일 경로}. 체험 고객이면 표시용 샘플을 자동 첨부한다."""
        docs, attached = self.docs(), {}
        uploaded = {r["doc_key"] for r in self.db.all("SELECT doc_key FROM evidence WHERE application_id = ? AND source = 'UPLOAD'", (self.app_id,))}
        with self.db.tx():
            if auto_link:
                consent.gate(self.db, self.app_id, "PUBLIC", "소득·재직 자동 연동", self.app_id)
            for d in docs:
                if files and d["key"] in files:
                    info = evidence.inspect_file(files[d["key"]])
                    attached[d["key"]] = info
                    evidence.save(self.db, self.app_id, d, "UPLOAD", info, [] if info["ok"] else ["DOC-INVALID"])
                elif d["key"] in uploaded:  # upload_doc 로 이미 올린 파일
                    attached[d["key"]] = {"ok": True}
                elif auto_link and d["auto"]:
                    attached[d["key"]] = {"ok": True}
                    evidence.save(self.db, self.app_id, d, "API", None, [])
                elif use_demo and self.scenario:
                    attached[d["key"]] = {"ok": True}
                    evidence.save(self.db, self.app_id, d, "DEMO", {"name": d["sample"], "size": 180000, "sha256": None}, [])
            self.defects = self._judge_docs(docs, attached)
            transition(self.db, self.app_id, "DOCS_SUBMITTED", "C04")
        return self.defects

    def _judge_docs(self, docs: list[dict], attached: dict[str, dict]) -> list[str]:
        refi_expired = any(t.get("flags", {}).get("doc_expired") for t in self.targets)
        return evidence.judge(docs, attached, (self.scenario or {}).get("defects", []), refi_expired)

    def upload_doc(self, doc_key: str, filename: str, data: bytes) -> list[str]:
        """C04 증빙 파일 1건 접수(source=UPLOAD). 파일 종류는 시그니처로 정하고, 올린 이름은 표시용으로만 저장한다. 결함 코드를 돌려준다."""
        if self.status() not in ("PROFILED", "DOCS_REQUIRED"):  # submit_docs 가 DOCS_SUBMITTED 로 갈 수 있는 상태에서만
            raise InvalidTransition()
        docs = self.docs()
        doc = next((d for d in docs if d["key"] == doc_key), None)
        if doc is None:
            raise ValidationError("제출할 수 없는 서류입니다.")
        if self.db.one("SELECT COUNT(*) AS n FROM evidence WHERE application_id = ? AND source = 'UPLOAD'", (self.app_id,))["n"] >= K.MAX_UPLOADS_PER_APP:
            raise ValidationError(f"업로드할 수 있는 파일은 신청 1건당 {K.MAX_UPLOADS_PER_APP}개까지입니다.")
        ext = evidence.inspect_bytes(data)
        info = {"name": evidence.safe_name(filename, ext), "size": len(data), "sha256": sha256(data)}
        with self.db.tx():
            evidence.write_upload(self.app_id, evidence.save(self.db, self.app_id, doc, "UPLOAD", info, []), ext, data)
        have = {r["doc_key"]: {"ok": True} for r in self.db.all("SELECT DISTINCT doc_key FROM evidence WHERE application_id = ?", (self.app_id,))}
        return self._judge_docs(docs, have)

    # ------------------------------------------------------------------ C05 심사
    def run_review(self):
        with self.db.tx():
            consent.gate(self.db, self.app_id, "CB", "대출 심사", self.app_id)
            transition(self.db, self.app_id, "UNDER_REVIEW", "C05")
            r = review(self.product, self.applicant, self.defects, self.excluded_monthly(), self.suit_override)
            self.db.insert("review_result", {"review_id": new_id("rvw"), "application_id": self.app_id, "result_code": r.result,
                                             "approved_limit": r.limit, "est_rate": str(r.rate), "dsr": str(r.dsr.quantize(D("0.0001"))),
                                             "credit_score": self.applicant.score, "hard_codes": r.hard, "cond_codes": r.cond, "doc_codes": r.docs,
                                             "stages": [list(s) for s in r.stages], "rule_version": "UW-PIPELINE@1", "reviewer_id": None, "created_at": now_iso()})
            transition(self.db, self.app_id, r.result, "C05")
        self.review = r
        return r

    # ------------------------------------------------------------------ C06 결과·추천 / 대환 비교
    def recommend(self) -> list[dict]:
        a, r = self.applicant, self.review
        amount = min(a.amount, r.limit)
        pref = self.db.one("SELECT rate_pref FROM applicant_profile WHERE application_id = ?", (self.app_id,))["rate_pref"]
        return recommendation.recommend(self.db, self.app_id, self.product, amount, a.term, a.repay, r.rate, a.income, pref)

    def choose(self, candidate: dict) -> None:
        self.chosen_rate = candidate["rate"]
        self.db.execute("UPDATE recommendation_log SET chosen_variant = ? WHERE application_id = ?", (candidate["variant"], self.app_id))

    def compare(self, confirm_unfavorable: bool = False) -> dict:
        res = refinance.benefit(self.db, self.app_id, self.product, self.targets, self.review.rate, self.applicant.term, self.applicant.repay)
        if res["verdict"] != "BENEFICIAL":
            if not confirm_unfavorable:
                return res
            self.db.insert("refi_override", {"override_id": new_id("rfo"), "application_id": self.app_id, "verdict": res["verdict"],
                                             "notice_version": "RF-10@1", "confirmed_at": now_iso()})
        self.refi_result, self.chosen_rate = res, self.review.rate
        return res

    # ------------------------------------------------------------------ C07 조건
    def set_terms(self, amount: int | None = None, term: int | None = None, repay: str | None = None, payment_day: int = 25,
                  debit_account_id: int | None = None, auth_ref: str | None = None) -> dict:
        p, a, r = self.product, self.applicant, self.review
        amount = refinance.refi_amount(self.targets) if self.refi else (amount or min(a.amount, r.limit))
        if not self.refi and amount > min(r.limit, p["max_amount"]):
            raise LimitExceeded(f"승인 한도({r.limit:,}원)를 넘을 수 없습니다.")
        if amount < p["min_amount"]:
            raise ValidationError("상품 최소 금액보다 작습니다.")
        term = term or a.term
        repay = repay or a.repay
        if term not in p["term_options"] or repay not in p["repay_options"]:
            raise ValidationError("상품이 허용하지 않는 기간·상환 방법입니다.")
        int_range(payment_day, "납입일", 1, 28)
        if debit_account_id is not None and self.user_id is not None:
            account_service.checking_for(self.db.session, self.user_id, debit_account_id)  # 내 저축예금(active)만
        self.terms = {"amount": amount, "term": term, "repay": repay, "payment_day": payment_day, "debit_account_id": debit_account_id}
        with self.db.tx():
            self.db.execute("DELETE FROM loan_terms WHERE application_id = ?", (self.app_id,))
            self.db.insert("loan_terms", {"application_id": self.app_id, "amount": amount, "term_months": term, "repay_method": repay,
                                          "payment_day": payment_day, "auto_debit_account_id": debit_account_id, "payroll_deduction": 0, "updated_at": now_iso()})
            consent.record(self.db, self.app_id, "AUTO_DEBIT", True, auth_ref)
            transition(self.db, self.app_id, "TERMS_SET", "C07")
        return self.terms

    # ------------------------------------------------------------------ C08 금리
    def price(self, prefs: list[str] | None = None) -> D:
        prefs = prefs if prefs is not None else ["AUTO_DEBIT"]
        usage = self._card_usage() if "CARD_USAGE" in prefs else None
        denied = []
        if usage and not usage["ok"]:  # 카드 사용 실적이 모자라면 그 우대는 빼고 알린다
            prefs = [p for p in prefs if p != "CARD_USAGE"]
            denied = [{"code": "CARD_USAGE", "usage": usage["amount"], "required": K.CARD_USAGE_MIN,
                       "message": f"직전 달 카드 사용액 {usage['amount']:,}원이 기준 {K.CARD_USAGE_MIN:,}원에 못 미쳐 카드 사용 우대는 적용되지 않았습니다."}]
        self.pref_result = {"applied": [p for p in prefs if p in C.PREFS], "denied": denied}
        r0 = self.chosen_rate or self.review.rate
        cut = sum((C.PREFS[p][0] for p in prefs if p in C.PREFS), D(0))
        final = max(D(str(self.product["rate_min"])) - D("0.3"), r0 - cut).quantize(D("0.01"))
        final = min(final, K.LEGAL_MAX_RATE)
        fee = None
        if self.agency:
            fee = self.db.one("SELECT fee_rate FROM guarantee_rule WHERE agency = ?", (self.agency,))["fee_rate"]
        with self.db.tx():
            self.db.execute("DELETE FROM pricing_preference WHERE application_id = ?", (self.app_id,))
            self.db.execute("DELETE FROM pricing WHERE application_id = ?", (self.app_id,))
            self.db.insert("pricing", {"application_id": self.app_id, "base_rate": str(K.BASE_RATE), "spread": str(r0 - K.BASE_RATE),
                                       "preferential": str(cut), "final_rate": str(final), "rate_type": "변동", "guarantee_fee_rate": fee, "created_at": now_iso()})
            for p in prefs:
                if p in C.PREFS:
                    self.db.insert("pricing_preference", {"preference_id": new_id("prf"), "application_id": self.app_id, "pref_code": p,
                                                          "rate_cut": str(C.PREFS[p][0]), "account_id": None,
                                                          "card_id": usage["card_id"] if usage and p == "CARD_USAGE" else None, "created_at": now_iso()})
            transition(self.db, self.app_id, "PRICED", "C08")
        self.final_rate = final
        return final

    def _card_usage(self) -> dict | None:
        """카드 사용 우대 확인(프로토타입 명세 "카드 사용 월 30만원 이상"): 내 사용 중(active) 카드의 직전 달(KST) 승인액 − 취소액 합계가 기준 이상인지, 근거 카드와 함께 돌려준다.
        shortcut: 카드가 여러 장이면 합산하고 근거 카드는 사용액이 가장 큰 1장이다. 회원이 없는 콘솔·시험은 확인할 수 없어 None(우대를 그대로 적용, 근거 카드 없음)."""
        if self.user_id is None:
            return None
        this_month = account_service.today_kst().replace(day=1)
        start, end = (datetime.combine(d, time.min, account_service.KST) for d in ((this_month - timedelta(days=1)).replace(day=1), this_month))
        net = func.coalesce(func.sum(case((m.CardTransaction.kind == "approval", m.CardTransaction.amount), else_=-m.CardTransaction.amount)), 0)
        rows = self.db.session.execute(
            select(m.Card.id, net).outerjoin(m.CardTransaction, and_(m.CardTransaction.card_id == m.Card.id, m.CardTransaction.occurred_at >= start, m.CardTransaction.occurred_at < end))
            .where(m.Card.user_id == self.user_id, m.Card.status == "active").group_by(m.Card.id).order_by(m.Card.issued_at, m.Card.id)).all()
        amount = int(sum(r[1] for r in rows))
        return {"ok": amount >= K.CARD_USAGE_MIN, "amount": amount, "card_id": max(rows, key=lambda r: r[1])[0] if rows else None}

    def quiz(self) -> list[tuple[str, str]]:
        q = list(QUIZ)
        q.append(("대환 시 기존 대출의 중도상환수수료는 은행이 대신 내 준다.", "X") if self.refi else ("계약일로부터 3년 안에 중도상환해도 수수료는 전혀 없다.", "X"))
        if self.product["business_type"] == "POLICY":
            q.append(("정책자금 대출 중 추가로 주택을 사면 대출금이 회수될 수 있다.", "O"))
        return q

    # ------------------------------------------------------------------ C09 설명의무
    def explain(self, scrolled: bool, answers: list[str]) -> bool:
        q = self.quiz()
        ok = scrolled and len(answers) == len(q) and all(a.upper() == x[1] for a, x in zip(answers, q))
        if not ok:
            raise ValidationError("설명서를 끝까지 읽고 이해 확인 문제를 모두 맞혀야 진행됩니다.")
        with self.db.tx():
            self.db.insert("explanation_record", {"explanation_id": new_id("exp"), "application_id": self.app_id,
                                                  "form_no": "RF-13" if self.refi else "LN-10", "scrolled_to_end": 1,
                                                  "quiz_results": answers, "created_at": now_iso()})
            transition(self.db, self.app_id, "EXPLAINED", "C09")
        return True

    # ------------------------------------------------------------------ C10 약정
    def sign_contract(self, confirmations: list[bool], signature_ref: str | None = None) -> str:
        need = 5 if self.refi else 4
        if len(confirmations) < need or not all(confirmations[:need]):
            raise ValidationError("약정 확인 항목을 모두 체크해야 전자서명할 수 있습니다.")
        cno = contract_no(self.refi, date.today().year)
        with self.db.tx():
            self.db.insert("contract", {"contract_no": cno, "application_id": self.app_id, "signed_at": now_iso(),
                                        "doc_hash": sha256(f"{cno}|{self.terms}|{self.final_rate}"), "signature_ref": signature_ref, "created_at": now_iso()})
            start = date.today()
            for row in schedule(self.terms["amount"], self.final_rate, self.terms["term"], self.terms["repay"], start):
                self.db.insert("repayment_schedule", {"contract_no": cno, **{**row, "due_date": row["due_date"].isoformat()}})
            transition(self.db, self.app_id, "CONTRACTED", "C10", actor="customer")
        self.contract = cno
        return cno

    # ------------------------------------------------------------------ C11 담보
    def needs_collateral(self) -> bool:
        return "collateral" in self.flow

    def set_collateral(self) -> None:
        cat = self.product["collateral_type"]
        with self.db.tx():
            self.db.insert("collateral", {"collateral_id": new_id("col"), "contract_no": self.contract, "collateral_type": cat,
                                          "detail": {"agency": self.agency} if self.agency else {}, "registration_no": None,
                                          "status": "SET", "registered_at": now_iso(), "released_at": None})
            if self.agency:
                self.db.execute("UPDATE guarantee_request SET status = 'ISSUED', cert_no = ?, issued_at = ? WHERE application_id = ?",
                                (f"G-{self.contract}", now_iso(), self.app_id))
            transition(self.db, self.app_id, "COLLATERAL_SET", "C11")

    # ------------------------------------------------------------------ C12 실행
    def execute(self, idempotency_key: str, fail_at: str | None = None, account_id: int | None = None) -> str:
        """멱등 키로 이중 실행을 막는다. 대환은 사가로 실행하고 실패 시 보상 후 REFI_FAILED.
        account_id 는 본인 지급(SELF) 대출금을 받을 내 저축예금이다. 주면 같은 트랜잭션에서 입금한다."""
        if self.db.one("SELECT 1 FROM idempotency_key WHERE idem_key = ?", (idempotency_key,)):
            raise DuplicateRequest()
        failed: SagaFailed | None = None
        with self.db.tx():
            self.db.insert("idempotency_key", {"idem_key": idempotency_key, "scope": "EXECUTE", "result_ref": self.contract, "created_at": now_iso()})
            if self.refi:
                try:
                    refinance.execute_saga(self.db, self.app_id, self.contract, self.targets, fail_at)
                except SagaFailed as exc:
                    # 실패 상태와 보상 기록은 남겨야 하므로 트랜잭션 안에서 잡아 저장하고, 밖에서 다시 알린다
                    transition(self.db, self.app_id, "REFI_FAILED", "C12")
                    failed = exc
            if failed is None:
                self._finish_execute(idempotency_key, account_id)
        if failed:
            raise failed
        return self.contract

    def _finish_execute(self, idempotency_key: str, account_id: int | None = None) -> None:
        """실행 후 처리: 지급(대출) · 대출 계좌 개설 · 상태 완료 · 알림."""
        if not self.refi:
            payee = {"CREDIT": "SELF", "DEPOSIT": "SELF", "JEONSE": "LANDLORD", "MORTGAGE": "SELLER", "AUTO": "DEALER"}[self.product["collateral_type"]]
            txn = None
            if payee == "SELF" and account_id is not None and self.user_id is not None:
                txn = account_service.loan_disburse(self.db.session, self.user_id, account_id, self.terms["amount"], self.contract)
            else:
                account_id = None  # 임대인·매도인·딜러 지급은 타행 계좌라 우리 계좌에 기록하지 않는다
            self.db.insert("disbursement", {"disbursement_id": new_id("dsb"), "contract_no": self.contract, "payee_type": payee,
                                            "payee_masked": "본인 계좌" if payee == "SELF" else "지급처(마스킹)", "account_id": account_id,
                                            "account_txn_ref": txn, "amount": self.terms["amount"], "result": "DONE",
                                            "idempotency_key": idempotency_key, "executed_at": now_iso()})
        self.account_no = loan_account_no()
        start = date.today()
        self.db.insert("loan_account", {"contract_no": self.contract, "user_id": self.user_id, "account_masked": mask_account(self.account_no),
                                        "account_hash": keyed_hash(self.account_no), "product_id": self.product["product_id"], "status": "ACTIVE",
                                        "principal": self.terms["amount"], "balance": self.terms["amount"], "rate": str(self.final_rate),
                                        "term_months": self.terms["term"], "repay_method": self.terms["repay"], "start_date": start.isoformat(),
                                        "next_due_date": add_months(start, 1).isoformat(), "debit_account_id": self.terms.get("debit_account_id"), "updated_at": now_iso()})
        transition(self.db, self.app_id, "DISBURSED", "C12")
        if self.refi:
            transition(self.db, self.app_id, "PAID_OFF", "C12x")
        transition(self.db, self.app_id, "COMPLETED", "C13")
        self.db.insert("notification", {"notification_id": new_id("ntf"), "user_id": self.user_id, "application_id": self.app_id,
                                        "contract_no": self.contract, "event_code": "DISBURSED",
                                        "message": "대출 실행이 완료되었습니다. 청약철회는 14일 안에 할 수 있습니다.", "sent_at": now_iso()})

    def monthly(self) -> int:
        return to_won(monthly_payment(self.terms["amount"], self.final_rate, self.terms["term"], self.terms["repay"]))
