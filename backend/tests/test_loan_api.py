"""대출 API 흐름 점검: 로그인 → 신청(신용대출, 체험 고객) → 실행(계좌 입금) → 내 대출·중도상환·타인 접근 차단·오류 코드.

주의: DB 를 바꾸는 시나리오가 들어 있다. 시험 DB 로 돌린다(앱이 시작할 때 테이블과 시드를 만든다).
  DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5433/aimbank python -m pytest backend/tests/test_loan_api.py
"""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

USERS = {"user1": ("Test1234!", "482915"), "user2": ("Test5678!", "739204")}
ANSWERS = ["O", "O", "X"]  # 일반대출 이해 확인 문제 3개의 정답(화면에는 정답을 내려주지 않는다)


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


def apply_until_contract(c: TestClient, debit_account_id=1) -> str:
    app_id = c.post("/api/loans/applications", json={"productId": "g1", "scenarioKey": "KIM_OK"}).json()["applicationId"]
    base = f"/api/loans/applications/{app_id}"
    req = c.get(f"{base}/consents").json()["required"]
    assert c.post(f"{base}/consents", json={"agreed": {r["code"]: True for r in req}}).status_code == 200
    assert c.post(f"{base}/profile", json={"ackUnsuitable": True}).status_code == 200
    assert c.post(f"{base}/docs", json={}).status_code == 200
    assert c.post(f"{base}/review").json()["result"] == "APPROVED"
    cands = c.get(f"{base}/recommendations").json()["items"]
    assert c.post(f"{base}/choose", json={"variant": cands[0]["variant"]}).status_code == 200
    assert c.post(f"{base}/terms", json={"debitAccountId": debit_account_id}).status_code == 200
    assert c.post(f"{base}/price", json={}).status_code == 200
    assert len(c.get(f"{base}/quiz").json()["items"]) == 3
    assert c.post(f"{base}/explain", json={"scrolled": True, "answers": ANSWERS}).status_code == 200
    assert c.post(f"{base}/contract", json={"confirmations": [True] * 5}).status_code == 200
    return app_id


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
