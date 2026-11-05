"""[역할] 대출 서비스 회귀·보안 테스트: 21개 정답표, 동의 게이트, 상태 전이, SQL 가드, 마스킹, 멱등성, 사가 보상, 감사 로그, 파일 검사."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Loan_main import open_db  # noqa: E402
from loan import calculators as calc  # noqa: E402
from loan import management as M  # noqa: E402
from loan.application import Session, product_row  # noqa: E402
from loan.consent import gate  # noqa: E402
from loan.errors import (ConsentMissing, DuplicateRequest, InvalidTransition, LimitExceeded,  # noqa: E402
                         RateLimited, SagaFailed, ValidationError)
from loan.evidence import inspect_file  # noqa: E402
from loan.llm_gateway import validate  # noqa: E402
from loan.scenarios import EXPECTED, run_all, run_one  # noqa: E402
from loan.security import RateLimiter, contains_pii, keyed_hash, mask_account, mask_pii  # noqa: E402
from loan.state_machine import transition  # noqa: E402
from loan.validation import clean_text, desired_amount, employee_no  # noqa: E402


_OPEN = []


def fresh_db():
    db = open_db(":memory:")
    _OPEN.append(db)
    return db


def tearDownModule():
    for db in _OPEN:
        db.close()


def until_execute(db, pid, scn):
    """실행 직전(약정 완료)까지 진행한 세션."""
    s = Session.start(db, pid, scn)
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


class ScenarioTests(unittest.TestCase):
    def test_21_scenarios_match_expected(self):
        db = fresh_db()
        rows = run_all(db)
        bad = [(r["product"], r["scenario"], r["result"], r["expected"]) for r in rows if not r["match"]]
        self.assertEqual(bad, [])
        self.assertEqual(len(rows), len(EXPECTED))
        # 승인·유리 건은 모두 대출 계좌까지 만들어진다
        self.assertEqual(db.one("SELECT COUNT(*) n FROM loan_account")["n"], sum(r["expected"] in ("APPROVED", "BENEFICIAL", "TRADE_OFF") for r in rows))

    def test_rejection_codes(self):
        db = fresh_db()
        self.assertIn("DSR-OVER", run_one(db, "g3", "NAM_BAD")["codes"])
        self.assertIn("REFI-DELINQ", run_one(db, "r1", "KIM_BAD")["codes"])

    def test_llm_outputs_pass_validation(self):
        db = fresh_db()
        run_all(db, complete=False)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM llm_call_log WHERE fallback_used = 1")["n"], 0)


class GuardrailTests(unittest.TestCase):
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
        self.assertIsNone(db.one("SELECT 1 FROM loan_account"))

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


class ExecutionTests(unittest.TestCase):
    def test_idempotent_execute(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK")
        s.execute("same-key")
        with self.assertRaises(DuplicateRequest):
            s.execute("same-key")
        self.assertEqual(db.one("SELECT COUNT(*) n FROM disbursement WHERE contract_no = ?", (s.contract,))["n"], 1)

    def test_refi_saga_compensation(self):
        for step in ("EXECUTE", "TRANSFER", "CONFIRM"):
            db = fresh_db()
            s = until_execute(db, "r1", "KIM_OK")
            with self.assertRaises(SagaFailed):
                s.execute(f"k-{step}", fail_at=step)
            self.assertEqual(s.status(), "REFI_FAILED")
            self.assertEqual(db.one("SELECT status FROM saga_instance WHERE application_id = ?", (s.app_id,))["status"], "COMPENSATED")
            self.assertIsNone(db.one("SELECT 1 FROM disbursement WHERE contract_no = ? AND result = 'DONE'", (s.contract,)))
            self.assertIsNone(db.one("SELECT 1 FROM loan_account"))

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


class AuditAndCalcTests(unittest.TestCase):
    def test_audit_chain_and_append_only(self):
        db = fresh_db()
        run_one(db, "g1", "KIM_OK")
        ok, n = db.verify_audit_chain()
        self.assertTrue(ok)
        self.assertGreater(n, 5)
        with self.assertRaises(sqlite3.DatabaseError):
            db.conn.execute("UPDATE audit_log SET action = 'X' WHERE audit_seq = 2")
        with self.assertRaises(sqlite3.DatabaseError):
            db.conn.execute("DELETE FROM audit_log")
        # 트리거를 우회해 직접 고쳐도 해시 체인 검사에서 걸린다
        db.conn.execute("DROP TRIGGER trg_audit_log_no_update")
        db.conn.execute("UPDATE audit_log SET action = 'TAMPERED' WHERE audit_seq = 2")
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
