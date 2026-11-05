"""카드 API 시나리오 (기획서 docs/card 의 T-번호 중 핵심). 실행: cd backend && python -m tests.card_api_scenarios

임시 DB(cardtest)와 임시 서버(8001)를 직접 띄우고 끝나면 지운다. 개발 DB 는 건드리지 않는다.
PostgreSQL(docker compose up -d)이 떠 있어야 한다. 기준 데이터는 seed.py (오늘 = 2026-11-04 기준 값).
user1 로 로그인한 쿠키 세션으로 요청하고, 쓰기 요청 전에 간편비밀번호를 확인한다(공통.md 4장).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, text

ADMIN_URL = "postgresql+psycopg://aimbank:aimbank@localhost:5432/postgres"
TEST_URL = "postgresql+psycopg://aimbank:aimbank@localhost:5432/cardtest"
BASE = "http://127.0.0.1:8001/api"
fails: list[str] = []
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))  # 로그인 쿠키를 들고 있는 브라우저 하나


def call(method, path, body=None, headers=None, browser=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with (browser or opener).open(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, "" if cond else info)
    if not cond:
        fails.append(name)


def apply_body(**over):
    body = {"type": "credit", "productId": "prod_credit_01", "paymentAccountId": "acc_002",
            "incomeRange": "20m_40m", "cardPin": "1357", "recipient": "김민수", "phone": "010-1234-5678",
            "address": {"line1": "서울"}, "agreements": {"cardTerms": True, "privacy": True, "creditInquiry": True}}
    body.update(over)
    return body


def apply(body, key=None):
    return call("POST", "/card-applications", body, {"Idempotency-Key": key or str(uuid.uuid4())})


def login_user1(browser=None):
    s, d = call("POST", "/auth/login", {"loginId": "user1", "password": "Test1234!"}, browser=browser)
    check("00 user1 로그인", s == 200, d)


def verify_pin():
    s, d = call("POST", "/auth/pin/verify", {"pin": "482915"})
    check("00 간편비밀번호 확인", s == 200 and d["validForSeconds"] == 300, d)


def parallel(*fns):
    with ThreadPoolExecutor(len(fns)) as pool:
        return [f.result() for f in [pool.submit(fn) for fn in fns]]


# ───── 01 ~ 05 조회 ─────
def read_scenarios():
    s, d = call("GET", "/cards", browser=urllib.request.build_opener())
    check("00 로그인 없이는 401 LOGIN_REQUIRED", s == 401 and d["code"] == "LOGIN_REQUIRED", d)
    login_user1()
    s, d = call("GET", "/cards/card_002")
    check("01 상세: 이용 1,208,000 / 40.3%", d["limit"] == {"total": 3000000, "used": 1208000, "remaining": 1792000, "usageRate": 40.3}, d)
    s, d = call("GET", "/cards/card_900")
    check("01 남의 카드는 404", s == 404 and d["code"] == "CARD_NOT_FOUND", d)
    s, d = call("GET", "/cards")
    check("01 정렬 정상→정지→분실, 해지는 제외", [c["id"] for c in d["items"]] == ["card_002", "card_001", "card_003", "card_004"] and d["terminatedCount"] == 1, d)
    s, d = call("GET", "/cards?includeTerminated=x")
    check("01 includeTerminated 형식 오류", s == 400, d)
    s, d = call("GET", "/card-transactions?cardId=card_002&from=2026-10-01&to=2026-10-31")
    check("02 T01 10월 조회", [i["id"] for i in d["items"]] == ["tx_206", "tx_204", "tx_203", "tx_202"] and d["summary"] == {"approvalTotal": 912000, "cancelTotal": 12000, "netTotal": 900000, "count": 4} and d["nextCursor"] is None, d)
    s, d = call("GET", "/card-transactions?cardId=card_002&from=2026-10-01&to=2026-10-31&kind=cancel")
    check("02 T02 취소만", d["summary"]["netTotal"] == -12000 and len(d["items"]) == 1, d)
    s, d = call("GET", "/card-transactions?from=2026-11-01&to=2026-11-04&merchant=gs25")
    check("02 T06 가맹점 대소문자 무시", [i["id"] for i in d["items"]] == ["tx_207"], d)
    s, d = call("GET", "/card-transactions?from=2026-11-03&to=2026-11-02")
    check("02 T12 FROM_AFTER_TO", s == 400 and d["details"]["fields"][0]["reason"] == "FROM_AFTER_TO", d)
    s, d = call("GET", "/card-transactions?from=2025-11-03&to=2026-11-04")
    check("02 T13 PERIOD_TOO_LONG", s == 400 and d["details"]["fields"][0]["reason"] == "PERIOD_TOO_LONG", d)
    s, d = call("GET", "/card-transactions?from=2025-11-04&to=2026-11-04")
    check("02 T14 정확히 12개월은 허용", s == 200, d)
    s, p1 = call("GET", "/card-transactions?cardId=card_001&from=2026-10-01&to=2026-10-31&limit=20")
    s, p2 = call("GET", "/card-transactions?cardId=card_001&from=2026-10-01&to=2026-10-31&limit=20&cursor=" + p1["nextCursor"])
    check("02 페이지 나누기 20+10, 합계 465,000", len(p1["items"]) == 20 and len(p2["items"]) == 10 and p2["nextCursor"] is None and p1["items"][0]["id"] == "tx_130" and p2["items"][-1]["id"] == "tx_101" and p1["summary"]["approvalTotal"] == 465000)
    s, d = call("GET", "/card-transactions?cardId=card_002&from=2026-10-01&to=2026-10-31&cursor=" + p1["nextCursor"])
    check("02 조건이 바뀐 커서는 INVALID_CURSOR", s == 400 and d["code"] == "INVALID_CURSOR", d)
    s, d = call("GET", "/card-transactions?from=2026-10-01&to=2026-10-31&cursor=" + p1["nextCursor"][:-3] + "abc")
    check("02 변조된 커서는 INVALID_CURSOR", s == 400 and d["code"] == "INVALID_CURSOR", d)
    s, d = call("GET", "/card-transactions/tx_204")
    check("02 취소 거래 상세에 원 승인", d["original"]["id"] == "tx_203", d)
    s, d = call("GET", "/card-transactions/tx_900")
    check("02 없는 거래 404", s == 404 and d["code"] == "TRANSACTION_NOT_FOUND", d)
    s, d = call("GET", "/card-billing/upcoming")
    pay = d["payments"]
    check("03 결제일 11/25 두 묶음, acc_002 부족 850,000", d["nextPaymentDate"] == "2026-11-25" and d["thisMonthTotal"] == 945000 and [p["amount"] for p in pay] == [45000, 900000] and pay[1]["shortfall"] == 850000 and pay[1]["balanceStatus"] == "insufficient", d)
    s, d = call("GET", "/cards/card_004/limit")
    check("05 분실 카드 한도 9.0%", d["credit"]["usageRate"] == 9.0 and d["credit"]["remaining"] == 455000, d)
    s, d = call("GET", "/cards/card_001/limit")
    check("05 체크카드 1회·1일 한도", d["debit"] == {"perTx": 1000000, "perDay": 3000000} and d["credit"] is None, d)
    s, d = call("GET", "/cards/card_005/limit")
    check("05 해지 카드는 409", s == 409 and d["code"] == "CARD_STATE_INVALID", d)


# ───── 04 정지·분실 ─────
def status_scenarios():
    s, d = call("POST", "/cards/card_002/suspend", {})
    check("04 본인 재확인 전에는 403 PIN_VERIFICATION_REQUIRED", s == 403 and d["code"] == "PIN_VERIFICATION_REQUIRED", d)
    s, d = call("GET", "/cards/card_002")
    check("04 재확인 실패로 상태는 그대로", d["status"] == "active", d)
    verify_pin()
    s, d = call("POST", "/cards/card_002/suspend", {})
    check("04 정지", s == 200 and d["status"] == "suspended" and d["suspendedAt"], d)
    s, d = call("POST", "/cards/card_002/suspend", {})
    check("04 이미 정지면 409", s == 409 and d["details"]["currentStatus"] == "suspended", d)
    s, d = call("POST", "/cards/card_002/resume", {})
    check("04 해제", s == 200 and d["status"] == "active" and d["suspendedAt"] is None, d)
    r = parallel(lambda: call("POST", "/cards/card_002/suspend", {}),
                 lambda: call("POST", "/cards/card_002/suspend", {}))
    check("04 T22 정지 동시 2건: 200 하나, 409 하나", sorted(x[0] for x in r) == [200, 409], r)
    call("POST", "/cards/card_002/resume", {})
    s, d = call("POST", "/cards/card_002/report-lost", {})
    check("04 분실 사유 누락은 400", s == 400, d)
    s, d = call("POST", "/cards/card_900/suspend", {})
    check("04 남의 카드 정지는 404", s == 404, d)


# ───── 06 신청 ─────
def apply_scenarios():
    s, d = call("GET", "/card-applications/eligibility")
    check("06 자격 조회: 신용 2장·체크 1장", d["types"]["credit"]["currentCount"] == 2 and d["types"]["debit"]["currentCount"] == 1, d)
    unverified = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    login_user1(unverified)
    s, d = call("POST", "/card-applications", apply_body(), {"Idempotency-Key": str(uuid.uuid4())}, browser=unverified)
    check("06 본인 재확인 전 신청은 403 PIN_VERIFICATION_REQUIRED", s == 403 and d["code"] == "PIN_VERIFICATION_REQUIRED", d)
    s, d = call("POST", "/cards/card_001/terminate", {"acknowledged": True}, browser=unverified)
    check("07 본인 재확인 전 해지는 403 PIN_VERIFICATION_REQUIRED", s == 403 and d["code"] == "PIN_VERIFICATION_REQUIRED", d)
    s, d = call("POST", "/card-applications", apply_body())
    check("06 키 없으면 IDEMPOTENCY_KEY_REQUIRED", s == 400 and d["code"] == "IDEMPOTENCY_KEY_REQUIRED", d)
    s, d = apply(apply_body(productId="prod_debit_01"))
    check("06 T22 상품·종류 불일치", s == 400 and {"field": "productId", "reason": "PRODUCT_TYPE_MISMATCH"} in d["details"]["fields"], d)
    s, d = apply(apply_body(cardPin="1234", phone="1"))
    check("06 여러 필드 오류를 모두 담음", s == 400 and len(d["details"]["fields"]) == 2, d)
    s, d = apply(apply_body(paymentAccountId="acc_101"))
    check("06 남의 계좌 404", s == 404 and d["code"] == "ACCOUNT_NOT_FOUND", d)
    s, d = apply(apply_body(incomeRange="lt_10m"))
    check("06 소득 부족 거절(201)", s == 201 and d["status"] == "rejected" and d["rejectReason"] == "INCOME_INSUFFICIENT" and d["card"] is None, d)

    # T40: 신용 2장 보유 → 서로 다른 키로 동시에 2건 → 하나만 승인
    r = parallel(lambda: apply(apply_body()), lambda: apply(apply_body()))
    ok = [x for x in r if x[0] == 201]
    check("06 T40 동시 신청: 하나만 승인, 다른 하나 409", len(ok) == 1 and any(x[0] == 409 and x[1]["code"] == "CARD_COUNT_LIMIT_EXCEEDED" for x in r), r)
    approved = ok[0][1]
    check("06 승인 응답: 한도 300만, 결제일 기본 25", approved["status"] == "approved" and approved["grantedLimit"] == 3000000 and approved["card"]["paymentDay"] == 25, approved)

    # 같은 키: 재시도는 같은 응답, 다른 본문은 422, 동시 2건은 카드 1장만
    key = str(uuid.uuid4())
    dbody = {k: v for k, v in apply_body(type="debit", productId="prod_debit_01").items() if k != "incomeRange"}
    dbody["agreements"] = {"cardTerms": True, "privacy": True}
    r = parallel(lambda: apply(dbody, key), lambda: apply(dbody, key))
    check("06 같은 키 동시 2건: 같은 응답, 카드는 1장만", r[0][0] == 201 and r[0] == r[1], r)
    s, again = apply(dbody, key)
    check("06 같은 키 재시도는 저장된 응답", s == 201 and again == r[0][1], again)
    s, d = apply({**dbody, "recipient": "다른이"}, key)
    check("06 같은 키에 다른 본문은 422", s == 422 and d["code"] == "IDEMPOTENCY_KEY_REUSED", d)
    s, d = call("GET", "/card-applications/eligibility")
    check("06 체크 보유가 2장으로(중복 발급 없음)", d["types"]["debit"]["currentCount"] == 2, d)

    s, d = apply(dbody)
    s2, d2 = apply(dbody)
    check("06 체크 3장째 승인, 4번째 409", s == 201 and s2 == 409 and d2["details"] == {"type": "debit", "current": 3, "max": 3}, (d, d2))
    last4 = [c["numberMasked"][-4:] for c in call("GET", "/cards?includeTerminated=true")[1]["items"]]
    check("06 T41 카드 끝 4자리 중복 없음", len(last4) == len(set(last4)), last4)
    return approved["card"]["id"]


# ───── 07 해지 ─────
def terminate_scenarios(new_card_id):
    s, d = call("GET", "/cards/card_002/termination-check")
    check("07 해지 불가 안내", d["unpaidAmount"] == 1208000 and d["firstDueDate"] == "2026-11-25" and not d["canTerminate"], d)
    s, d = call("POST", "/cards/card_002/terminate", {"acknowledged": True})
    check("07 미결제가 있으면 409", s == 409 and d["code"] == "CARD_TERMINATE_BLOCKED_UNPAID", d)
    s, d = call("POST", f"/cards/{new_card_id}/terminate", {"acknowledged": False})
    check("07 유의사항 미확인 400", s == 400, d)
    s, d = call("POST", f"/cards/{new_card_id}/terminate", {"reason": "unused", "acknowledged": True})
    check("07 해지", s == 200 and d["status"] == "terminated", d)
    s, d = call("POST", f"/cards/{new_card_id}/terminate", {"acknowledged": True})
    check("07 이미 해지면 409", s == 409 and d["code"] == "CARD_STATE_INVALID", d)
    s, d = call("GET", "/cards?includeTerminated=true")
    check("07 해지 카드는 목록 끝에, 상세 응답에 해지 사유 없음", d["items"][-1]["status"] == "terminated" and "terminatedReason" not in json.dumps(d), d)


def main():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS cardtest"))
        c.execute(text("CREATE DATABASE cardtest"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8001"],
        env={**os.environ, "DATABASE_URL": TEST_URL}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen("http://127.0.0.1:8001/api/health")
                break
            except OSError:
                time.sleep(0.5)
        read_scenarios()
        status_scenarios()
        terminate_scenarios(apply_scenarios())
    finally:
        server.terminate()
        server.wait()
        with admin.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS cardtest"))
    print(f"FAILS {len(fails)}" if fails else "ok")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
