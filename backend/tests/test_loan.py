"""[역할] 대출 서비스 회귀·보안 테스트: 21개 정답표, 동의 게이트, 상태 전이, SQL 가드, 마스킹, 멱등성, 사가 보상, 감사 로그, 파일 검사, 자동이체 배치·연체·계좌 변경, 신청 상태 복원, 카드 사용 우대, 증빙 업로드."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

import psycopg
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as DbSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models as m  # noqa: E402
from app.accounts import service as account_service  # noqa: E402
from app.loan import calculators as calc  # noqa: E402
from app.loan import config as loan_config  # noqa: E402
from app.loan import management as M  # noqa: E402
from app.loan.application import Session, product_row  # noqa: E402
from app.loan.consent import gate  # noqa: E402
from app.loan.database import Database  # noqa: E402
from app.loan.errors import (ConsentMissing, DuplicateRequest, InvalidTransition, LimitExceeded,  # noqa: E402
                             NotFound, RateLimited, SagaFailed, ValidationError)
from app.loan.evidence import inspect_bytes, inspect_file  # noqa: E402
from app.loan.llm_gateway import validate  # noqa: E402
from app.loan.scenarios import EXPECTED, run_all, run_one  # noqa: E402
from app.loan.security import RateLimiter, contains_pii, keyed_hash, mask_account, mask_pii  # noqa: E402
from app.loan.state_machine import transition  # noqa: E402
from app.loan.validation import clean_text, desired_amount, employee_no  # noqa: E402
from app.migrations import upgrade_head  # noqa: E402
from app.seed import seed as seed_app  # noqa: E402

# 시험은 개발 DB 를 건드리지 않도록 전용 스키마(loan_test)에 마이그레이션을 돌려 테이블을 새로 만들고, 각 시험은 트랜잭션을 되돌려 서로 영향을 주지 않는다.
# 실행(개발 DB aimbank, 5432 를 그대로 써도 된다):  python -m pytest backend/tests/test_loan.py
URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank")
ENGINE = create_engine(URL, connect_args={"options": "-c search_path=loan_test"})
_OPEN: list = []


def setUpModule():
    with ENGINE.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS loan_test CASCADE"))
        c.execute(text("CREATE SCHEMA loan_test"))
    with ENGINE.begin() as c:
        upgrade_head(c)  # 실제 마이그레이션으로 테이블을 만든다(alembic upgrade head)
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


def until_execute(db, pid, scn, user_id=None, debit_account_id=None):
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
    s.set_terms(debit_account_id=debit_account_id)
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
    def test_precheck_ineligible_is_a_result_not_an_error(self):
        db = fresh_db()
        s = Session.start(db, "p1", None)
        res = s.precheck(False, False, 900_000_000, 900_000_000)  # 자격 미충족 입력도 오류가 아니라 판정 결과로 돌려준다
        self.assertFalse(all(ok for _, ok, _ in res))
        self.assertEqual(db.one("SELECT status FROM loan_application WHERE application_id = ?", (s.app_id,))["status"], "POLICY_INELIGIBLE")

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
    """대출 지급·상환이 계좌(accounts·transactions)와 한 트랜잭션으로 움직이는지: 공통.md 8장, dev/account/backend-spec.md 7.3 loan_disbursement·loan_repayment."""

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


class AutoDebitTests(LoanCase):
    """월 상환 자동이체 배치(M.auto_debit)와 저축예금 해지 검사(count_active_debit_loans)."""

    @staticmethod
    def bal(db, aid):
        return db.one("SELECT balance FROM accounts WHERE id = ?", (aid,))["balance"]

    def loan(self, db, debit_account_id=1, user_id=1):
        s = until_execute(db, "g1", "KIM_OK", user_id=user_id, debit_account_id=debit_account_id)
        s.execute("k-ad", account_id=1 if user_id == 1 else debit_account_id)
        acc = M.account(db, s.contract)
        return s.contract, acc, date.fromisoformat(acc["next_due_date"]), date.fromisoformat(acc["start_date"])

    def test_pays_installment_once_per_due_date_and_advances(self):
        db = fresh_db()
        no, acc, due, start = self.loan(db)
        self.assertEqual(due, calc.add_months(start, 1))  # 첫 납입일 = 상환 스케줄 1회차
        self.assertEqual(M.auto_debit(db.session, due - timedelta(days=1)), 0)  # 납입일 전에는 받지 않는다
        before = self.bal(db, 1)
        row = calc.schedule(acc["balance"], D(str(acc["rate"])), acc["term_months"], acc["repay_method"], start)[0]
        self.assertEqual(M.auto_debit(db.session, due), 1)
        self.assertEqual(M.auto_debit(db.session, due), 0)  # 같은 날 다시 돌려도 이중 출금이 없다
        self.assertEqual(self.bal(db, 1), before - row["principal"] - row["interest"])
        t = db.one("SELECT * FROM transactions WHERE ref_id = ? AND type = 'loan_repayment'", (no,))
        self.assertEqual((t["ref_type"], t["amount"]), ("loan", row["principal"] + row["interest"]))
        p = db.one("SELECT * FROM payment_txn WHERE contract_no = ?", (no,))
        self.assertEqual((p["method"], p["result"], p["due_date"], p["account_txn_ref"]), ("AUTO_DEBIT", "DONE", due.isoformat(), t["id"]))
        after = M.account(db, no)
        self.assertEqual((after["balance"], after["next_due_date"]), (acc["balance"] - row["principal"], calc.add_months(start, 2).isoformat()))
        # 서버가 꺼져 밀린 회차는 한 번에 따라잡는다(2·3회차)
        self.assertEqual(M.auto_debit(db.session, calc.add_months(start, 3)), 2)
        self.assertEqual(M.account(db, no)["next_due_date"], calc.add_months(start, 4).isoformat())

    def test_short_balance_stays_unpaid_and_retries(self):
        db = fresh_db()
        no, acc, due, _ = self.loan(db, debit_account_id=2)  # 계좌 2 는 500,000원뿐이라 월 상환액에 모자란다
        before = self.bal(db, 2)
        for _ in range(2):  # 다음 실행에서 다시 시도해도 미납 기록은 납입일당 1건이다
            self.assertEqual(M.auto_debit(db.session, due), 0)
        self.assertEqual(self.bal(db, 2), before)
        self.assertEqual(M.account(db, no)["balance"], acc["balance"])
        self.assertEqual(M.account(db, no)["next_due_date"], due.isoformat())
        rows = db.all("SELECT result, allocation FROM payment_txn WHERE contract_no = ?", (no,))
        self.assertEqual([(r["result"], r["allocation"]) for r in rows], [("FAILED", '{"reason": "INSUFFICIENT_BALANCE"}')])
        db.execute("UPDATE accounts SET balance = 5000000 WHERE id = 2")
        self.assertEqual(M.auto_debit(db.session, due), 1)
        self.assertGreater(M.account(db, no)["next_due_date"], due.isoformat())

    def test_last_installment_pays_off(self):
        db = fresh_db()
        no, acc, due, start = self.loan(db)
        db.execute("UPDATE accounts SET balance = 1000000000 WHERE id = 1")
        self.assertEqual(M.auto_debit(db.session, calc.add_months(start, acc["term_months"])), acc["term_months"])
        end = M.account(db, no)
        self.assertEqual((end["status"], end["balance"], end["next_due_date"]), ("PAID_OFF", 0, None))

    def test_close_blocker_counts_active_debit_loans(self):
        db = fresh_db()
        user = db.session.get(m.User, 4)  # 계좌 6 은 연결된 예적금·카드가 없는 user4 의 저축예금
        self.assertEqual(M.count_active_debit_loans(db.session, 6), 0)
        self.assertIsNone(account_service.preview_close(db.session, user, 6)["blocker"])
        no, *_ = self.loan(db, debit_account_id=6, user_id=4)
        self.assertEqual(M.count_active_debit_loans(db.session, 6), 1)
        self.assertEqual(account_service.preview_close(db.session, user, 6)["blocker"]["code"], "ACCOUNT_LINKED_LOAN")
        with self.assertRaises(HTTPException) as ctx:
            account_service.close_account(db.session, user, 6)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["code"]), (409, "ACCOUNT_LINKED_LOAN"))
        M.withdraw(db, no)  # 철회하면 더는 진행 중 대출이 아니다
        self.assertEqual(M.count_active_debit_loans(db.session, 6), 0)

    def test_failed_debit_goes_overdue_then_clears_with_penalty(self):
        db = fresh_db()
        no, acc, due, _ = self.loan(db, debit_account_id=2)  # 계좌 2 는 500,000원뿐이라 월 상환액에 모자란다
        dlq = lambda: db.one("SELECT * FROM delinquency WHERE contract_no = ?", (no,))
        self.assertEqual(M.auto_debit(db.session, due), 0)
        self.assertEqual(M.account(db, no)["status"], "OVERDUE")
        d = dlq()
        row = calc.schedule(acc["balance"], D(str(acc["rate"])), acc["term_months"], acc["repay_method"], date.fromisoformat(acc["start_date"]))[0]
        self.assertEqual((d["start_date"], d["days"], d["amount"], d["stage"]), (due.isoformat(), 0, row["principal"] + row["interest"], "D1"))
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM notification WHERE contract_no = ? AND event_code = 'OVERDUE'", (no,))["n"], 1)
        # 같은 날 다시 돌려도, 며칠 뒤에 다시 돌려도 연체 기록·미납 기록·안내는 늘지 않고 일수만 갱신된다
        self.assertEqual(M.auto_debit(db.session, due), 0)
        self.assertEqual(M.auto_debit(db.session, due + timedelta(days=5)), 0)
        d = dlq()
        self.assertEqual((d["days"], d["stage"], [n["code"] for n in json.loads(d["notices"])]), (5, "D5", ["OVERDUE", "OVERDUE_REMIND"]))
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM delinquency WHERE contract_no = ?", (no,))["n"], 1)
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM payment_txn WHERE contract_no = ? AND result = 'FAILED'", (no,))["n"], 1)
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM notification WHERE contract_no = ? AND event_code LIKE 'OVERDUE%'", (no,))["n"], 2)
        # 연체 중에도 중도상환 견적은 나오고, 지연배상금은 전액 상환 견적에만 붙는다
        penalty = calc.to_won(D(row["principal"]) * (D(str(acc["rate"])) + loan_config.LATE_ADD) / 100 * 5 / 365)
        with mock.patch.object(account_service, "today_kst", return_value=due + timedelta(days=5)):
            self.assertEqual(M.overdue_info(db, M.account(db, no))["penalty"], penalty)
            self.assertEqual(M.prepay_quote(M.account(db, no), 1_000_000, db)["penalty"], 0)
            self.assertEqual(M.prepay_quote(M.account(db, no), acc["balance"], db)["penalty"], penalty)
        with self.assertRaises(ValidationError):
            M.extend(db, no, 12)  # 연체 중에는 그 밖의 관리 업무는 막힌다
        db.execute("UPDATE accounts SET balance = 5000000 WHERE id = 2")
        before = self.bal(db, 2)
        self.assertEqual(M.auto_debit(db.session, due + timedelta(days=5)), 1)  # 지연배상금을 얹어 받고 연체가 풀린다
        self.assertEqual(self.bal(db, 2), before - row["principal"] - row["interest"] - penalty)
        self.assertEqual(M.auto_debit(db.session, due + timedelta(days=5)), 0)  # 이중 출금 없음
        after = M.account(db, no)
        self.assertEqual((after["status"], after["balance"]), ("ACTIVE", acc["balance"] - row["principal"]))
        self.assertEqual((dlq()["stage"], dlq()["days"]), ("RESOLVED", 5))
        p = db.one("SELECT amount, allocation FROM payment_txn WHERE contract_no = ? AND result = 'DONE'", (no,))
        self.assertEqual((p["amount"], json.loads(p["allocation"])["penalty"]), (row["principal"] + row["interest"] + penalty, penalty))

    def test_overdue_loan_can_be_paid_off_but_partial_prepay_keeps_it_overdue(self):
        db = fresh_db()
        no, acc, due, _ = self.loan(db, debit_account_id=2)
        self.assertEqual(M.auto_debit(db.session, due), 0)  # 연체
        db.execute("UPDATE accounts SET balance = 50000000 WHERE id = 2")
        M.prepay(db, no, 1_000_000, "pp-partial", account_id=2)
        self.assertEqual(M.account(db, no)["status"], "OVERDUE")
        bal = M.account(db, no)["balance"]
        with mock.patch.object(account_service, "today_kst", return_value=due + timedelta(days=3)):
            q = M.prepay_quote(M.account(db, no), bal, db)
            res = M.prepay(db, no, bal, "pp-overdue", account_id=2)
        self.assertEqual((res["total"], q["penalty"] > 0, res["balance"]), (q["total"], True, 0))
        self.assertEqual(M.account(db, no)["status"], "PAID_OFF")
        self.assertEqual(db.one("SELECT stage FROM delinquency WHERE contract_no = ?", (no,))["stage"], "RESOLVED")

    def test_change_auto_debit_account(self):
        db = fresh_db()
        no, acc, due, _ = self.loan(db, debit_account_id=1)
        self.assertEqual(M.change_auto_debit(db, no, 1, 2), {"contract_no": no, "debit_account_id": 2})
        self.assertEqual(M.account(db, no)["debit_account_id"], 2)
        self.assertEqual(db.one("SELECT auto_debit_account_id AS a FROM loan_terms WHERE application_id = (SELECT application_id FROM contract WHERE contract_no = ?)", (no,))["a"], 2)
        self.assertEqual((M.count_active_debit_loans(db.session, 1), M.count_active_debit_loans(db.session, 2)), (0, 1))
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM loan_audit_log WHERE entity_id = ? AND action = 'AUTO_DEBIT_CHANGE'", (no,))["n"], 1)
        b1 = self.bal(db, 1)
        db.execute("UPDATE accounts SET balance = 5000000 WHERE id = 2")
        self.assertEqual(M.auto_debit(db.session, due), 1)  # 다음 출금부터 새 계좌에서 나간다
        self.assertEqual((self.bal(db, 1), self.bal(db, 2) < 5_000_000), (b1, True))
        # 남의 계좌·저축예금이 아닌 계좌·남의 대출은 안 된다
        with self.assertRaises(HTTPException) as ctx:
            M.change_auto_debit(db, no, 1, 5)
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            M.change_auto_debit(db, no, 1, 3)  # 계좌 3 은 정기예금
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["code"]), (409, "ACCOUNT_STATE_INVALID"))
        with self.assertRaises(NotFound):
            M.change_auto_debit(db, no, 2, 5)
        self.assertEqual(M.account(db, no)["debit_account_id"], 2)
        M.withdraw(db, no)
        with self.assertRaises(ValidationError):
            M.change_auto_debit(db, no, 1, 1)  # 철회된 대출


class SessionRestoreTests(LoanCase):
    """신청 진행 상태를 DB 에 남겼다가(session_state) 메모리 없이 되살려 이어서 진행한다."""

    @staticmethod
    def save(db, s):
        db.update("loan_application", {"application_id": s.app_id}, {"session_state": s.snapshot()})

    def test_restore_and_finish(self):
        db = fresh_db()  # 한 시험에서 fresh_db 를 두 번 열면 감사 로그 advisory lock 을 서로 기다린다
        for pid, scn in (("g1", "KIM_OK"), ("r1", "KIM_OK")):  # 신용대출과 대환(대상·기존 대출 상태 포함)
            s = until_execute(db, pid, scn, user_id=1)
            self.save(db, s)
            r = Session.restore(db, s.app_id, 1)
            review = replace(s.review, stages=[list(x) for x in s.review.stages])  # JSON 을 거치면 단계 튜플이 리스트가 된다
            self.assertEqual((r.applicant, r.review, r.final_rate, r.chosen_rate, r.terms, r.contract, r.targets, r.existing),
                             (s.applicant, review, s.final_rate, s.chosen_rate, s.terms, s.contract, s.targets, s.existing), pid)
            self.assertEqual(r.flow, s.flow)
            self.assertEqual(r.execute(f"k-restore-{pid}", account_id=None if r.refi else 1), s.contract)
            self.assertEqual(r.status(), "COMPLETED")
            self.assertIsNone(Session.restore(db, s.app_id, 1), pid)  # 끝난 신청은 되살리지 않는다

    def test_restore_is_owner_only_and_skips_expired(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK", user_id=1)
        self.assertIsNone(Session.restore(db, s.app_id, 2))
        self.assertIsNotNone(Session.restore(db, s.app_id, 1))
        db.execute("UPDATE loan_application SET expires_at = now() - interval '1 day' WHERE application_id = ?", (s.app_id,))
        self.assertIsNone(Session.restore(db, s.app_id, 1))

    def test_restore_keeps_recommendation_candidates(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK", user_id=1)
        s.give_consents({c: True for c in s.required_consents()})
        s.submit_profile({}, ack_unsuitable=True)
        s.submit_docs()
        s.run_review()
        s.cands = s.recommend()
        self.save(db, s)
        r = Session.restore(db, s.app_id, 1)
        self.assertEqual(r.cands, s.cands)  # Decimal 도 다시 Decimal 이다
        r.choose(r.cands[0])
        self.assertEqual(r.chosen_rate, s.cands[0]["rate"])

    def test_restore_without_snapshot_is_fresh_session(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK", user_id=1)
        r = Session.restore(db, s.app_id, 1)
        self.assertEqual((r.status(), r.applicant, r.review, r.terms, r.cands), ("DRAFT", None, None, {}, []))


def use_card(db, card_id, amount, cancel_of=None):
    """직전 달 10일(KST)에 카드 거래 1건을 넣는다(시드 거래의 날짜와 상관없이 카드 사용 우대 기준을 시험한다). (카드 id, 거래 id)"""
    last = account_service.today_kst().replace(day=1) - timedelta(days=1)
    tx = m.CardTransaction(card_id=card_id, kind="cancel" if cancel_of else "approval", occurred_at=datetime.combine(last.replace(day=10), time(12), account_service.KST),
                           merchant="시험 가맹점", amount=amount, original_id=cancel_of)
    db.session.add(tx)
    db.session.flush()
    return card_id, tx.id


class CardUsageTests(LoanCase):
    """카드 사용 우대(CARD_USAGE): 내 사용 중 카드의 직전 달 사용액(승인 − 취소)이 30만원 이상일 때만 −0.1%p."""

    @staticmethod
    def priced(s, prefs):
        s.set_terms()  # 금리 확정을 다시 하려면 조건 확정 단계로 돌아간다
        return s.price(prefs)

    def test_card_cut_needs_last_month_usage(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK", user_id=2)  # 회원 2 는 사용 중 카드 card_900 한 장, 거래 없음
        s.give_consents({c: True for c in s.required_consents()})
        s.submit_profile({}, ack_unsuitable=True)
        s.submit_docs()
        s.run_review()
        s.choose(s.recommend()[0])
        base = self.priced(s, ["AUTO_DEBIT"])
        self.assertEqual(self.priced(s, ["AUTO_DEBIT", "CARD_USAGE"]), base)  # 사용 실적 없음: 우대 없음
        self.assertEqual(s.pref_result["applied"], ["AUTO_DEBIT"])
        self.assertEqual([(d["code"], d["usage"], d["required"]) for d in s.pref_result["denied"]], [("CARD_USAGE", 0, 300_000)])
        self.assertEqual([r["pref_code"] for r in db.all("SELECT pref_code FROM pricing_preference WHERE application_id = ?", (s.app_id,))], ["AUTO_DEBIT"])
        _, ap = use_card(db, "card_900", 400_000)
        self.assertEqual(self.priced(s, ["AUTO_DEBIT", "CARD_USAGE"]), base - D("0.10"))  # 기준 이상: 우대
        self.assertEqual((s.pref_result["applied"], s.pref_result["denied"]), (["AUTO_DEBIT", "CARD_USAGE"], []))
        self.assertEqual(db.one("SELECT card_id FROM pricing_preference WHERE application_id = ? AND pref_code = 'CARD_USAGE'", (s.app_id,))["card_id"], "card_900")
        use_card(db, "card_900", 150_000, cancel_of=ap)  # 취소하면 순 사용액 250,000원: 다시 기준 미달
        self.assertEqual(self.priced(s, ["AUTO_DEBIT", "CARD_USAGE"]), base)
        self.assertEqual(s.pref_result["denied"][0]["usage"], 250_000)


class ExternalRefTests(LoanCase):
    """로그인·카드 연동 칸: auth_ref, signature_ref, card_id."""

    def test_refs_are_stored(self):
        db = fresh_db()
        s = Session.start(db, "g1", "KIM_OK", user_id=1, auth_ref="login:100")
        s.give_consents({c: True for c in s.required_consents()}, "login:100")
        s.submit_profile({}, ack_unsuitable=True)
        s.submit_docs()
        s.run_review()
        s.choose(s.recommend()[0])
        s.set_terms(auth_ref="login:100")
        card = use_card(db, "card_001", 5_000_000)[0]  # 직전 달 사용액이 기준을 넘고 가장 많은 카드(시드 거래 날짜와 상관없이)
        s.price(["AUTO_DEBIT", "CARD_USAGE"])
        s.explain(True, [a for _, a in s.quiz()])
        s.sign_contract([True] * 5, "pin:200")
        self.assertEqual(db.one("SELECT auth_ref FROM loan_application WHERE application_id = ?", (s.app_id,))["auth_ref"], "login:100")
        refs = {r["auth_ref"] for r in db.all("SELECT auth_ref FROM consent_record WHERE application_id = ?", (s.app_id,))}
        self.assertEqual(refs, {"login:100"})  # 필수 동의와 자동이체 동의 모두
        self.assertEqual(db.one("SELECT signature_ref FROM contract WHERE contract_no = ?", (s.contract,))["signature_ref"], "pin:200")
        cards = {r["pref_code"]: r["card_id"] for r in db.all("SELECT pref_code, card_id FROM pricing_preference WHERE application_id = ?", (s.app_id,))}
        self.assertEqual(cards, {"AUTO_DEBIT": None, "CARD_USAGE": card})

    def test_refs_stay_null_without_values(self):
        db = fresh_db()
        s = until_execute(db, "g1", "KIM_OK")  # 콘솔·시험: 회원도 없다
        self.assertEqual(db.one("SELECT auth_ref, signature_ref FROM loan_application a JOIN contract c USING (application_id) WHERE a.application_id = ?", (s.app_id,)),
                         {"auth_ref": None, "signature_ref": None})
        s2 = Session.start(db, "g1", "KIM_OK")
        s2.give_consents({c: True for c in s2.required_consents()})
        s2.submit_profile({}, ack_unsuitable=True)
        s2.submit_docs()
        s2.run_review()
        s2.choose(s2.recommend()[0])
        s2.set_terms()
        s2.price(["CARD_USAGE"])
        self.assertIsNone(db.one("SELECT card_id FROM pricing_preference WHERE application_id = ?", (s2.app_id,))["card_id"])


class UploadTests(LoanCase):
    """증빙 파일 업로드(Session.upload_doc): 시그니처·크기·개수 검사, 이름은 경로에 쓰지 않음, submit_docs 가 업로드를 제출로 센다."""
    PDF, PNG = b"%PDF-1.4\n" + b"x" * 100, b"\x89PNG\r\n\x1a\n" + b"x" * 100

    def profiled(self, db):
        s = Session.start(db, "g1", None, user_id=1)  # 체험 고객이 아니므로 샘플이 자동으로 붙지 않는다
        s.give_consents({c: True for c in s.required_consents()})
        s.submit_profile({}, ack_unsuitable=True)
        return s

    def test_upload_stores_file_and_counts_as_submitted(self):
        db = fresh_db()
        s = self.profiled(db)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(loan_config, "UPLOAD_DIR", Path(d)):
            self.assertIn("DOC-MISSING", s.upload_doc("income", "../../evil.pdf", self.PDF))  # 재직 서류가 아직 없다
            # 확장자가 pdf 여도 내용이 png 면 png 로 저장되고, 올린 이름의 경로 부분은 버린다
            self.assertEqual(s.upload_doc("emp", "C:\\x\\emp.pdf", self.PNG), [])
            rows = db.all("SELECT * FROM evidence WHERE application_id = ? ORDER BY evidence_id", (s.app_id,))
            self.assertEqual([(r["doc_key"], r["source"], r["file_name"], r["status"]) for r in rows],
                             [("income", "UPLOAD", "evil.pdf", "OK"), ("emp", "UPLOAD", "emp.pdf", "OK")])
            self.assertEqual(rows[0]["file_sha256"], hashlib.sha256(self.PDF).hexdigest())
            self.assertEqual([p.suffix for p in sorted(Path(d, s.app_id).iterdir())], [".pdf", ".png"])
            self.assertEqual(s.submit_docs(), [])  # 필수 서류를 업로드로 냈으니 DOC-MISSING 이 없다
            self.assertEqual(s.status(), "DOCS_SUBMITTED")
            with self.assertRaises(InvalidTransition):  # 제출이 끝난 뒤에는 올릴 수 없다
                s.upload_doc("income", "a.pdf", self.PDF)

    def test_rejects_bad_input(self):
        db = fresh_db()
        s = self.profiled(db)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(loan_config, "UPLOAD_DIR", Path(d)), \
                mock.patch.object(loan_config, "MAX_UPLOADS_PER_APP", 2):
            for data in (b"MZ\x90\x00 exe", b"", self.PDF + b"x" * loan_config.MAX_FILE_BYTES):  # 위장 파일, 빈 파일, 10MB 초과
                with self.assertRaises(ValidationError):
                    s.upload_doc("income", "a.pdf", data)
            with self.assertRaises(ValidationError):
                s.upload_doc("nope", "a.pdf", self.PDF)  # 이 상품에 없는 서류
            s.upload_doc("income", "a.pdf", self.PDF)
            s.upload_doc("income", "b.pdf", self.PDF)
            with self.assertRaises(ValidationError):  # 신청 1건당 개수 제한
                s.upload_doc("emp", "c.pdf", self.PDF)
            self.assertEqual(db.one("SELECT COUNT(*) n FROM evidence WHERE application_id = ?", (s.app_id,))["n"], 2)
            self.assertEqual(len(list(Path(d, s.app_id).iterdir())), 2)  # 거절된 파일은 디스크에 남기지 않는다
        with self.assertRaises(InvalidTransition):
            Session.start(db, "g1", None, user_id=1).upload_doc("income", "a.pdf", self.PDF)  # 고객 정보 확인 전

    def test_inspect_bytes_by_signature(self):
        self.assertEqual((inspect_bytes(self.PDF), inspect_bytes(self.PNG), inspect_bytes(b"\xff\xd8\xff\xe0JFIF")), (".pdf", ".png", ".jpg"))


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
