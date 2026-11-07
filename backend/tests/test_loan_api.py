"""대출 API 흐름 점검: 로그인 → 신청(신용대출, 체험 고객) → 실행(계좌 입금) → 내 대출·중도상환·타인 접근 차단·오류 코드, 서버 재시작 뒤 신청 복원, 증빙 업로드, 로그인·서명 참조.

주의: DB 를 바꾸는 시나리오가 들어 있다. 개발 DB 가 아니라 같은 서버(5432)의 시험 DB(aimbank_loantest)로 돌린다.
앱은 시작할 때 시드는 넣지만 테이블은 만들지 않으므로 먼저 마이그레이션한다(DB 는 없으면 psql -U postgres -c "CREATE DATABASE aimbank_loantest OWNER aimbank;").
  (backend 폴더) DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank_loantest alembic upgrade head
  DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank_loantest python -m pytest backend/tests/test_loan_api.py
"""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.loan import config as loan_config  # noqa: E402
from app.loan.router import _SESSIONS  # noqa: E402
from app.main import app  # noqa: E402

USERS = {"user1": ("Test1234!", "482915"), "user2": ("Test5678!", "739204")}
ANSWERS = ["O", "O", "X"]  # 일반대출 이해 확인 문제 3개의 정답(화면에는 정답을 내려주지 않는다)
PDF = b"%PDF-1.4\n" + b"x" * 50


@pytest.fixture(scope="module")
def server():
    with TestClient(app) as c:  # with 로 열어야 lifespan(테이블·시드)이 돈다
        yield c


def login(server, uid, verify=True) -> TestClient:
    c = TestClient(app)
    pw, pin = USERS[uid]
    assert c.post("/api/auth/login", json={"loginId": uid, "password": pw}).status_code == 200
    if verify:
        assert c.post("/api/auth/pin/verify", json={"pin": pin}).status_code == 200
    return c


def apply_until_contract(c: TestClient, debit_account_id=1, restart=False) -> str:
    def reboot():  # restart=True 면 요청마다 메모리의 진행 상태를 지운다(서버를 다시 켠 것과 같다): DB 에서 복원되어야 이어진다
        if restart:
            _SESSIONS.clear()

    app_id = c.post("/api/loans/applications", json={"productId": "g1", "scenarioKey": "KIM_OK"}).json()["applicationId"]
    base = f"/api/loans/applications/{app_id}"
    reboot()
    req = c.get(f"{base}/consents").json()["required"]
    assert c.post(f"{base}/consents", json={"agreed": {r["code"]: True for r in req}}).status_code == 200
    reboot()
    assert c.post(f"{base}/profile", json={"ackUnsuitable": True}).status_code == 200
    reboot()
    assert c.post(f"{base}/docs", json={}).status_code == 200
    reboot()
    assert c.post(f"{base}/review").json()["result"] == "APPROVED"
    reboot()
    cands = c.get(f"{base}/recommendations").json()["items"]
    reboot()  # 추천 후보도 DB 에서 복원되어 다시 조회하지 않고 고를 수 있다
    assert c.post(f"{base}/choose", json={"variant": cands[0]["variant"]}).status_code == 200
    reboot()
    assert c.post(f"{base}/terms", json={"debitAccountId": debit_account_id}).status_code == 200
    reboot()
    r = c.post(f"{base}/price", json={})
    assert r.status_code == 200 and (r.json()["appliedPrefs"], r.json()["deniedPrefs"]) == (["AUTO_DEBIT"], [])
    reboot()
    assert len(c.get(f"{base}/quiz").json()["items"]) == 3
    assert c.post(f"{base}/explain", json={"scrolled": True, "answers": ANSWERS}).status_code == 200
    reboot()
    assert c.post(f"{base}/contract", json={"confirmations": [True] * 5}).status_code == 200
    reboot()
    return app_id


def row(sql, **params):
    with SessionLocal() as s:
        return s.execute(text(sql), params).all()


def balance(c, aid=1) -> int:
    return c.get(f"/api/accounts/{aid}").json()["balance"]


def test_public_and_login_required(server):
    anon = TestClient(app)
    assert len(anon.get("/api/loans/products").json()["items"]) == 13
    r = anon.get("/api/loans")
    assert (r.status_code, r.json()["code"]) == (401, "LOGIN_REQUIRED")


def test_full_flow_credits_account_and_blocks_others(server):
    u1, u2 = login(server, "user1"), login(server, "user2", verify=False)
    before = balance(u1)
    app_id = apply_until_contract(u1)
    # 다른 회원은 내 신청을 찾을 수 없다(404)
    r = u2.get(f"/api/loans/applications/{app_id}")
    assert (r.status_code, r.json()["code"]) == (404, "LOAN_NOT_FOUND")
    key = {"Idempotency-Key": uuid.uuid4().hex}
    # 계좌를 안 고르면 400, 키가 없으면 400
    assert u1.post(f"/api/loans/applications/{app_id}/execute", json={}, headers=key).json()["code"] == "VALIDATION_FAILED"
    assert u1.post(f"/api/loans/applications/{app_id}/execute", json={"accountId": 1}).json()["code"] == "VALIDATION_FAILED"
    r = u1.post(f"/api/loans/applications/{app_id}/execute", json={"accountId": 1}, headers=key)
    assert r.status_code == 200, r.text
    no = r.json()["contractNo"]
    # 실행이 끝난 신청은 서버 메모리에서 지워져 다시 실행할 수 없다(같은 키의 중복 방지는 test_loan.py 가 확인)
    r = u1.post(f"/api/loans/applications/{app_id}/execute", json={"accountId": 1}, headers=key)
    assert (r.status_code, r.json()["code"]) == (404, "LOAN_NOT_FOUND")
    loan = u1.get(f"/api/loans/{no}").json()
    assert "accountHash" not in loan and "userId" not in loan  # 내부 값은 내려주지 않는다
    assert all("accountHash" not in x for x in u1.get("/api/loans").json()["items"])
    assert balance(u1) == before + loan["principal"]
    tx = u1.get("/api/accounts/1/transactions?period=custom&from=2000-01-01").json()["items"][0]
    assert (tx["type"], tx["direction"], tx["refType"], tx["refId"]) == ("loan_disbursement", "in", "loan", no)
    # 남의 대출은 404
    r = u2.get(f"/api/loans/{no}")
    assert (r.status_code, r.json()["code"]) == (404, "LOAN_NOT_FOUND")
    # 내 대출 목록과 메인 화면 요약에 보인다
    assert no in [x["contractNo"] for x in u1.get("/api/loans").json()["items"]]
    home = u1.get("/api/home").json()["loans"]
    assert home["count"] >= 3 and len(home["products"]) == 13
    # 중도상환: 간편비밀번호 확인 후 계좌에서 출금
    q = u1.get(f"/api/loans/{no}/prepay-quote?principal=1000000").json()
    r = u1.post(f"/api/loans/{no}/prepay", json={"principal": 1_000_000, "accountId": 1}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    assert balance(u1) == before + loan["principal"] - q["total"]


def test_change_auto_debit_account(server):
    u1, u2 = login(server, "user1", verify=False), login(server, "user2")
    app_id = apply_until_contract(u1)
    u1.post("/api/auth/pin/verify", json={"pin": USERS["user1"][1]})
    no = u1.post(f"/api/loans/applications/{app_id}/execute", json={"accountId": 1}, headers={"Idempotency-Key": uuid.uuid4().hex}).json()["contractNo"]
    detail = u1.get(f"/api/loans/{no}").json()
    assert (detail["debitAccountId"], detail["overdue"]) == (1, None)
    assert u1.get(f"/api/loans/{no}/prepay-quote?principal=1000000").json()["penalty"] == 0
    url = f"/api/loans/{no}/auto-debit"
    u1_nopin = login(server, "user1", verify=False)
    r = u1_nopin.put(url, json={"accountId": 2})
    assert (r.status_code, r.json()["code"]) == (403, "PIN_VERIFICATION_REQUIRED")
    r = u2.put(url, json={"accountId": 5})  # 남의 대출은 404
    assert (r.status_code, r.json()["code"]) == (404, "LOAN_NOT_FOUND")
    r = u1.put(url, json={"accountId": 5})  # 남의 계좌는 404
    assert (r.status_code, r.json()["code"]) == (404, "ACCOUNT_NOT_FOUND")
    r = u1.put(url, json={"accountId": 3})  # 정기예금은 자동이체 계좌가 될 수 없다
    assert (r.status_code, r.json()["code"]) == (409, "ACCOUNT_STATE_INVALID")
    assert u1.put(url, json={}).json()["code"] == "VALIDATION_FAILED"
    r = u1.put(url, json={"accountId": 2})
    assert (r.status_code, r.json()) == (200, {"contractNo": no, "debitAccountId": 2})
    assert u1.get(f"/api/loans/{no}").json()["debitAccountId"] == 2
    assert row("SELECT auto_debit_account_id FROM loan_terms t JOIN contract c USING (application_id) WHERE c.contract_no = :n", n=no)[0][0] == 2


def test_execute_requires_pin_verification(server):
    u1 = login(server, "user1", verify=False)
    app_id = apply_until_contract(u1)
    r = u1.post(f"/api/loans/applications/{app_id}/execute", json={"accountId": 1}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert (r.status_code, r.json()["code"]) == (403, "PIN_VERIFICATION_REQUIRED")


def test_step_errors_use_standard_codes(server):
    u1 = login(server, "user1")
    app_id = u1.post("/api/loans/applications", json={"productId": "g1", "scenarioKey": "KIM_OK"}).json()["applicationId"]
    # 동의 없이 심사로 가면 403, 앞 단계를 건너뛰면 409(서버 오류가 아니다), 필수 동의를 거부하면 403
    r = u1.post(f"/api/loans/applications/{app_id}/review")
    assert (r.status_code, r.json()["code"]) == (403, "LOAN_CONSENT_REQUIRED")
    for step in ("recommendations", "terms", "price", "contract", "collateral"):
        r = u1.get(f"/api/loans/applications/{app_id}/{step}") if step == "recommendations" else u1.post(f"/api/loans/applications/{app_id}/{step}", json={"confirmations": [True] * 5})
        assert (r.status_code, r.json()["code"]) == (409, "LOAN_STATE_INVALID"), step
    r = u1.post(f"/api/loans/applications/{app_id}/consents", json={"agreed": {}})
    assert (r.status_code, r.json()["code"]) == (403, "LOAN_CONSENT_REQUIRED")
    assert u1.post("/api/loans/applications", json={"productId": "nope"}).json()["code"] == "LOAN_NOT_FOUND"


def test_restart_between_steps_restores_application(server):
    u1, u2 = login(server, "user1"), login(server, "user2", verify=False)
    before = balance(u1)
    app_id = apply_until_contract(u1, restart=True)
    _SESSIONS.clear()
    assert u2.get(f"/api/loans/applications/{app_id}").json()["code"] == "LOAN_NOT_FOUND"  # 복원도 내 신청만
    got = u1.get(f"/api/loans/applications/{app_id}").json()
    assert (got["status"], got["finalRate"] is not None) == ("CONTRACTED", True)
    _SESSIONS.clear()
    r = u1.post(f"/api/loans/applications/{app_id}/execute", json={"accountId": 1}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    assert balance(u1) > before
    _SESSIONS.clear()  # 끝난 신청은 복원하지 않는다
    assert u1.get(f"/api/loans/applications/{app_id}").json()["code"] == "LOAN_NOT_FOUND"


def test_login_and_signature_refs(server):
    for verify, sig in ((True, "pin:"), (False, None)):
        app_id = apply_until_contract(login(server, "user1", verify=verify))
        auth, = row("SELECT auth_ref FROM loan_application WHERE application_id = :a", a=app_id)[0]
        assert auth.startswith("login:")
        assert {r[0] for r in row("SELECT auth_ref FROM consent_record WHERE application_id = :a", a=app_id)} == {auth}
        signature, = row("SELECT signature_ref FROM contract WHERE application_id = :a", a=app_id)[0]
        assert (signature.startswith(sig) if sig else signature is None)  # 약정 때 간편비밀번호를 확인하지 않았으면 비어 있다


def test_upload_doc_flow(server, tmp_path, monkeypatch):
    monkeypatch.setattr(loan_config, "UPLOAD_DIR", tmp_path)
    u1, u2 = login(server, "user1"), login(server, "user2", verify=False)
    app_id = u1.post("/api/loans/applications", json={"productId": "g1"}).json()["applicationId"]  # 체험 고객이 아니라 샘플이 붙지 않는다
    base = f"/api/loans/applications/{app_id}"
    url = f"{base}/docs/upload"

    def up(c, key, data=PDF, name="a.pdf"):
        return c.post(url, data={"docKey": key}, files={"file": (name, data, "application/pdf")})

    assert up(TestClient(app), "income").json()["code"] == "LOGIN_REQUIRED"
    assert up(u1, "income").json()["code"] == "LOAN_STATE_INVALID"  # 고객 정보 확인 전
    req = u1.get(f"{base}/consents").json()["required"]
    assert u1.post(f"{base}/consents", json={"agreed": {r["code"]: True for r in req}}).status_code == 200
    assert u1.post(f"{base}/profile", json={"ackUnsuitable": True}).status_code == 200
    r = up(u2, "income")
    assert (r.status_code, r.json()["code"]) == (404, "LOAN_NOT_FOUND")  # 남의 신청
    for bad in (up(u1, "income", b"MZ\x90\x00 exe"), up(u1, "income", b""), up(u1, "nope"), u1.post(url, data={"docKey": "income"})):
        assert (bad.status_code, bad.json()["code"]) == (400, "VALIDATION_FAILED")
    assert list(tmp_path.iterdir()) == []  # 거절된 파일은 저장하지 않는다
    r = up(u1, "income", name="../../evil.pdf")
    assert (r.status_code, r.json()["docKey"], "DOC-MISSING" in r.json()["defects"]) == (201, "income", True)
    r = up(u1, "emp")
    assert (r.status_code, r.json()["defects"]) == (201, [])
    assert len(list((tmp_path / app_id).iterdir())) == 2
    assert [x[0] for x in row("SELECT file_name FROM evidence WHERE application_id = :a AND source = 'UPLOAD' ORDER BY evidence_id", a=app_id)] == ["evil.pdf", "a.pdf"]
    r = u1.post(f"{base}/docs", json={})
    assert (r.status_code, r.json()["defects"], r.json()["status"]) == (200, [], "DOCS_SUBMITTED")
    assert up(u1, "income").json()["code"] == "LOAN_STATE_INVALID"  # 제출이 끝난 뒤
