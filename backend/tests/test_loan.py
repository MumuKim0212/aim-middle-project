"""[역할] 대출 서비스 회귀·보안 테스트: 21개 정답표, 동의 게이트, 상태 전이, SQL 가드, 마스킹, 멱등성, 사가 보상, 감사 로그, 파일 검사."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import psycopg
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as DbSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models as m  # noqa: E402
from app.loan import calculators as calc  # noqa: E402
from app.loan import management as M  # noqa: E402
from app.loan.application import Session, product_row  # noqa: E402
from app.loan.consent import gate  # noqa: E402
from app.loan.database import Database  # noqa: E402
from app.loan.errors import (ConsentMissing, DuplicateRequest, InvalidTransition, LimitExceeded,  # noqa: E402
                             RateLimited, SagaFailed, ValidationError)
from app.loan.evidence import inspect_file  # noqa: E402
from app.loan.llm_gateway import validate  # noqa: E402
from app.loan.scenarios import EXPECTED, run_all, run_one  # noqa: E402
from app.loan.security import RateLimiter, contains_pii, keyed_hash, mask_account, mask_pii  # noqa: E402
from app.loan.state_machine import transition  # noqa: E402
from app.loan.validation import clean_text, desired_amount, employee_no  # noqa: E402
from app.seed import seed as seed_app  # noqa: E402

# 시험은 개발 DB 를 건드리지 않도록 전용 스키마(loan_test)에 테이블을 새로 만들고, 각 시험은 트랜잭션을 되돌려 서로 영향을 주지 않는다.
# 실행(시험 DB):  DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5433/aimbank python -m pytest backend/tests/test_loan.py
URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank")
ENGINE = create_engine(URL, connect_args={"options": "-c search_path=loan_test"})
_OPEN: list = []


def setUpModule():
    with ENGINE.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS loan_test CASCADE"))
        c.execute(text("CREATE SCHEMA loan_test"))
    m.Base.metadata.create_all(ENGINE)
    with DbSession(ENGINE) as s:
        seed_app(s)  # 회원 1~4, 계좌 1~6, 대출 기준 데이터와 시연 대출 2건


def tearDownModule():
    ENGINE.dispose()


def fresh_db() -> Database:
    """시험 한 건용 DB. 끝나면(LoanCase.tearDown) 트랜잭션을 되돌린다."""
    conn = ENGINE.connect()
    trans = conn.begin()
    _OPEN.append((conn, trans))
    return Database(DbSession(bind=conn))


class LoanCase(unittest.TestCase):
    def tearDown(self):
        while _OPEN:
            conn, trans = _OPEN.pop()
            trans.rollback()
            conn.close()


def until_execute(db, pid, scn, user_id=None):
    """실행 직전(약정 완료)까지 진행한 세션."""
    s = Session.start(db, pid, scn, user_id=user_id)
    s.give_consents({c: True for c in s.required_consents()})
    if s.refi:
        s.fetch_existing()
        s.select_targets()
    s.submit_profile({}, ack_unsuitable=True)
    if s.flow_key == "INST_A":
        s.choose_guarantee()
    s.submit_docs()
    s.run_review()
    if s.refi:
        s.compare(confirm_unfavorable=True)
    else:
        s.choose(s.recommend()[0])
    s.set_terms()
    s.price()
    s.explain(True, [a for _, a in s.quiz()])
    s.sign_contract([True] * 5)
    if s.needs_collateral():
        s.set_collateral()
    return s


class ScenarioTests(LoanCase):
    def test_21_scenarios_match_expected(self):
        db = fresh_db()
        rows = run_all(db)
        bad = [(r["product"], r["scenario"], r["result"], r["expected"]) for r in rows if not r["match"]]
        self.assertEqual(bad, [])
        self.assertEqual(len(rows), len(EXPECTED))
        # 승인·유리 건은 모두 대출 계좌까지 만들어진다
        self.assertEqual(db.one("SELECT COUNT(*) n FROM loan_account WHERE user_id IS NULL")["n"], sum(r["expected"] in ("APPROVED", "BENEFICIAL", "TRADE_OFF") for r in rows))

    def test_rejection_codes(self):
        db = fresh_db()
        self.assertIn("DSR-OVER", run_one(db, "g3", "NAM_BAD")["codes"])
        self.assertIn("REFI-DELINQ", run_one(db, "r1", "KIM_BAD")["codes"])

    def test_llm_outputs_pass_validation(self):
        db = fresh_db()
        run_all(db, complete=False)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM llm_call_log WHERE fallback_used")["n"], 0)


class GuardrailTests(LoanCase):
    def test_consent_gate_blocks_and_logs(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK")
        with self.assertRaises(ConsentMissing):
            gate(db, s.app_id, "CB", "심사", s.app_id)
        self.assertEqual(db.one("SELECT status FROM inquiry_log WHERE application_id = ?", (s.app_id,))["status"], "BLOCKED")

    def test_required_consent_refused_stops_flow(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK")
        agreed = {c: True for c in s.required_consents()}
        agreed[next(iter(agreed))] = False
        with self.assertRaises(ConsentMissing):
            s.give_consents(agreed)

    def test_invalid_transition(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK")
        with self.assertRaises(InvalidTransition):
            transition(db, s.app_id, "DISBURSED", "C12")

    def test_cannot_execute_before_contract(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK")
        with self.assertRaises(Exception):
            s.execute("k-early")
        self.assertIsNone(db.one("SELECT 1 FROM loan_account WHERE user_id IS NULL"))

    def test_sql_guard(self):
        db = fresh_db()
        with self.assertRaises(TypeError):
            db.execute("SELECT * FROM product_catalog WHERE product_id = ?", "g1")   # 튜플이 아니면 거부
        with self.assertRaises(ValueError):
            db.execute("SELECT 1; DROP TABLE product_catalog")
        with self.assertRaises(ValueError):
            db.insert("product_catalog; DROP TABLE x", {"a": 1})
        with self.assertRaises(ValueError):
            db.insert("no_such_table", {"a": 1})                  # 스키마에 없는 테이블 거부
        with self.assertRaises(ValueError):
            db.update("loan_account", {}, {"balance": 0})         # WHERE 없는 전체 갱신 거부
        # 주입 문자열은 값으로만 취급된다
        self.assertIsNone(db.one("SELECT * FROM product_catalog WHERE product_id = ?", ("g1' OR '1'='1",)))
        self.assertIn("product_catalog", db.table_names())

    def test_input_validation(self):
        p = product_row(fresh_db(), "g1")
        with self.assertRaises(LimitExceeded) as cm:
            desired_amount(p["max_amount"] + 1, p)
        self.assertIn("한도금액을 초과하였습니다", cm.exception.user_message)
        with self.assertRaises(ValidationError):
            employee_no("A1'; DROP")
        with self.assertRaises(ValidationError):
            clean_text("<script>alert(1)</script>", "이름")

    def test_pii_masking(self):
        self.assertEqual(mask_account("110-123-456789").count("*") > 0, True)
        self.assertNotIn("900101-1234567", mask_pii("주민번호 900101-1234567 입니다"))
        self.assertTrue(contains_pii("010-1234-5678"))
        self.assertFalse(contains_pii("2026-11-05"))           # 날짜는 계좌로 오인하지 않는다
        self.assertNotEqual(keyed_hash("110-123-456789"), "110-123-456789")

    def test_account_number_not_stored_in_plain(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK")
        s.execute("k1")
        row = db.one("SELECT account_masked, account_hash FROM loan_account WHERE contract_no = ?", (s.contract,))
        self.assertNotEqual(row["account_masked"], s.account_no)
        self.assertIn("*", row["account_masked"])
        self.assertEqual(row["account_hash"], keyed_hash(s.account_no))

    def test_rate_limiter(self):
        rl = RateLimiter(limit=2, window_sec=60)
        rl.check("a")
        rl.check("a")
        with self.assertRaises(RateLimited):
            rl.check("a")

    def test_llm_validator_rejects_bad_output(self):
        bad = '{"items":[{"product_id":"X","reasons":["무조건 승인 보장 9.99%"],"cautions":[],"cited_facts":[]}]}'
        res = validate(bad, {"4.5"}, {"A"}, ["월 상환액"])
        self.assertFalse(res["V2_exists"] or res["V3_numbers"] or res["V5_banned"] or res["V6_required"])
        self.assertFalse(validate("not json", set(), set(), [])["V1_schema"])


class ExecutionTests(LoanCase):
    def test_idempotent_execute(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK")
        s.execute("same-key")
        with self.assertRaises(DuplicateRequest):
            s.execute("same-key")
        self.assertEqual(db.one("SELECT COUNT(*) n FROM disbursement WHERE contract_no = ?", (s.contract,))["n"], 1)

    def test_refi_saga_compensation(self):
        for step in ("EXECUTE", "TRANSFER", "CONFIRM"):
            self.tearDown()  # 감사 로그 advisory lock 은 트랜잭션이 끝나야 풀리므로 반복마다 되돌린다
            db = fresh_db()
            s = until_execute(db, "r1", "KIM_OK")
            with self.assertRaises(SagaFailed):
                s.execute(f"k-{step}", fail_at=step)
            self.assertEqual(s.status(), "REFI_FAILED")
            self.assertEqual(db.one("SELECT status FROM saga_instance WHERE application_id = ?", (s.app_id,))["status"], "COMPENSATED")
            self.assertIsNone(db.one("SELECT 1 FROM disbursement WHERE contract_no = ? AND result = 'DONE'", (s.contract,)))
            self.assertIsNone(db.one("SELECT 1 FROM loan_account WHERE user_id IS NULL"))

    def test_refi_success(self):
        db = fresh_db()
        s = until_execute(db, "r1", "KIM_OK")
        s.execute("k-ok")
        self.assertEqual(s.status(), "COMPLETED")
        self.assertTrue(db.one("SELECT 1 FROM payoff_record"))

    def test_prepay_idempotent_and_payoff(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK")
        s.execute("k2")
        bal = M.account(db, s.contract)["balance"]
        M.prepay(db, s.contract, 1_000_000, "pp-1")
        with self.assertRaises(DuplicateRequest):
            M.prepay(db, s.contract, 1_000_000, "pp-1")
        self.assertEqual(M.account(db, s.contract)["balance"], bal - 1_000_000)
        with self.assertRaises(ValidationError):
            M.prepay(db, s.contract, bal, "pp-2")                 # 잔액 초과
        M.prepay(db, s.contract, bal - 1_000_000, "pp-3")
        self.assertEqual(M.account(db, s.contract)["status"], "PAID_OFF")
        self.assertTrue(M.certificate(db, s.contract, "PAYOFF").startswith("CT-"))

    def test_management_rules(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK")
        s.execute("k3")
        with self.assertRaises(ValidationError):
            M.rate_cut(db, s.contract, [])
        with self.assertRaises(ValidationError):
            M.extend(db, s.contract, 5)
        with self.assertRaises(ValidationError):
            M.certificate(db, s.contract, "PAYOFF")              # 완제 전
        self.assertTrue(M.withdraw(db, s.contract)["accepted"])  # 실행 당일은 철회 가능
        with self.assertRaises(ValidationError):
            M.prepay(db, s.contract, 1000, "pp-x")              # 철회 후 거래 불가


class AccountIntegrationTests(LoanCase):
    """대출 지급·상환이 계좌(accounts·transactions)와 한 트랜잭션으로 움직이는지: 공통.md 8장, 계좌.md 7.3 loan_disbursement·loan_repayment."""

    @staticmethod
    def bal(db, aid):
        return db.one("SELECT balance FROM accounts WHERE id = ?", (aid,))["balance"]

    def test_disbursement_credits_my_account(self):
        db = fresh_db()
        before = self.bal(db, 1)
        s = until_execute(db, "g1", "KIM_OK", user_id=1)
        s.execute("k-acc", account_id=1)
        amount = s.terms["amount"]
        self.assertEqual(self.bal(db, 1), before + amount)
        t = db.one("SELECT * FROM transactions WHERE ref_id = ?", (s.contract,))
        self.assertEqual((t["type"], t["ref_type"], t["amount"], t["balance_after"]), ("loan_disbursement", "loan", amount, before + amount))
        d = db.one("SELECT account_id, account_txn_ref FROM disbursement WHERE contract_no = ?", (s.contract,))
        self.assertEqual((d["account_id"], d["account_txn_ref"]), (1, t["id"]))

    def test_other_users_account_is_404_and_nothing_changes(self):
        db = fresh_db()
        before = self.bal(db, 5)
        s = until_execute(db, "g1", "KIM_OK", user_id=1)
        with self.assertRaises(HTTPException) as ctx:
            s.execute("k-other", account_id=5)  # 계좌 5 는 user2 의 것
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.bal(db, 5), before)
        self.assertIsNone(db.one("SELECT 1 FROM loan_account WHERE contract_no = ?", (s.contract,)))

    def test_auto_debit_account_must_be_mine(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK", user_id=1)
        s.give_consents({c: True for c in s.required_consents()})
        s.submit_profile({}, ack_unsuitable=True)
        s.submit_docs()
        s.run_review()
        s.choose(s.recommend()[0])
        with self.assertRaises(HTTPException) as ctx:
            s.set_terms(debit_account_id=5)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_prepay_debits_account_and_blocks_when_short(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK", user_id=1)
        s.execute("k-pp", account_id=1)
        before = self.bal(db, 1)
        res = M.prepay(db, s.contract, 1_000_000, "pp-1", account_id=1)
        self.assertEqual(self.bal(db, 1), before - res["total"])
        t = db.one("SELECT * FROM transactions WHERE ref_id = ? AND type = 'loan_repayment'", (s.contract,))
        self.assertEqual((t["amount"], t["ref_type"]), (res["total"], "loan"))
        # 계좌 2 는 500,000원뿐이라 100만원 상환은 422 이고 대출 잔액은 그대로다
        loan_before = M.account(db, s.contract)["balance"]
        with self.assertRaises(HTTPException) as ctx:
            M.prepay(db, s.contract, 1_000_000, "pp-2", account_id=2)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["code"]), (422, "INSUFFICIENT_BALANCE"))
        self.assertEqual(M.account(db, s.contract)["balance"], loan_before)

    def test_withdrawal_takes_money_back_from_account(self):
        db = fresh_db()
        before = self.bal(db, 1)
        s = until_execute(db, "g1", "KIM_OK", user_id=1)
        s.execute("k-wd", account_id=1)
        res = M.withdraw(db, s.contract)
        self.assertTrue(res["accepted"])
        self.assertEqual(self.bal(db, 1), before + s.terms["amount"] - res["refund"])  # 받은 돈에서 원금+3일 이자를 돌려준다


class AuditAndCalcTests(LoanCase):
    def test_audit_chain_and_append_only(self):
        db = fresh_db()
        run_one(db, "g1", "KIM_OK")
        ok, n = db.verify_audit_chain()
        self.assertTrue(ok)
        self.assertGreater(n, 5)
        with self.assertRaises(psycopg.errors.RaiseException), db.tx():
            db.execute("UPDATE loan_audit_log SET action = 'X' WHERE audit_seq = (SELECT MIN(audit_seq) FROM loan_audit_log)")
        with self.assertRaises(psycopg.errors.RaiseException), db.tx():
            db.execute("DELETE FROM loan_audit_log")
        # 트리거를 우회해 직접 고쳐도 해시 체인 검사에서 걸린다
        db.execute("DROP TRIGGER trg_audit_log_no_update ON loan_audit_log")
        db.execute("UPDATE loan_audit_log SET action = 'TAMPERED' WHERE audit_seq = (SELECT MIN(audit_seq) + 1 FROM loan_audit_log)")
        self.assertFalse(db.verify_audit_chain()[0])

    def test_schedule_ends_at_zero(self):
        for method in ("원리금균등분할", "원금균등분할", "만기일시상환"):
            rows = calc.schedule(30_000_000, D("4.5"), 36, method, date.today())
            self.assertEqual(rows[-1]["balance_after"], 0, method)
            self.assertEqual(sum(r["principal"] for r in rows), 30_000_000, method)

    def test_kwon_format(self):
        self.assertEqual(calc.kwon(19_000_000), "1,900만원")
        self.assertTrue(calc.kwon(5_000).endswith("원"))


class FileCheckTests(unittest.TestCase):
    def test_magic_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d, "a.pdf")
            good.write_bytes(b"%PDF-1.4\n...")
            fake = Path(d, "b.pdf")
            fake.write_bytes(b"MZ\x90\x00 exe")
            exe = Path(d, "c.exe")
            exe.write_bytes(b"MZ")
            self.assertTrue(inspect_file(good)["ok"])
            self.assertFalse(inspect_file(fake)["ok"])
            self.assertFalse(inspect_file(exe)["ok"])
            with self.assertRaises(ValidationError):
                inspect_file(Path(d, "none.pdf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
