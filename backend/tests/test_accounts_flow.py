"""계좌 흐름 점검(계좌.md 9장 실패 시나리오 AF-xx). 실행 중인 서버에 HTTP 로 요청한다.

주의: 이체·개설·해지처럼 DB 를 바꾸는 시나리오가 들어 있다. 시험용 DB 로 띄운 서버에 돌리고, 같은 DB 를 스크립트에도 알려 준다
(자동이체·롤백 시나리오는 서비스 함수를 직접 부른다).
  서버(시험 DB):  DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5433/aimbank APP_ENV=dev \
                  python -m uvicorn app.main:app --port 8002
  실행:           DATABASE_URL=(같은 값) python tests/test_accounts_flow.py http://127.0.0.1:8002
처음 시드 상태(python reset_db.py --yes)에서만 전부 통과한다. 다시 돌리려면 시험 DB 를 초기화한다.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.accounts.interest import add_months  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002").rstrip("/")
USERS = {"user1": ("Test1234!", "482915"), "user2": ("Test5678!", "739204"), "user4": ("Test3456!", "264817")}


class Browser:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=15) as r:
                raw = r.read().decode() or "null"
                return r.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode() or "null"
            return e.code, json.loads(raw)

    def login(self, uid, verify=True):
        pw, pin = USERS[uid]
        assert self.call("POST", "/api/auth/login", {"loginId": uid, "password": pw})[0] == 200
        if verify:
            assert self.call("POST", "/api/auth/pin/verify", {"pin": pin})[0] == 200
        return self


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if not cond and detail else ""))


def code(res):
    return res[1].get("code") if isinstance(res[1], dict) else None


def bal(b, aid):
    return b.call("GET", f"/api/accounts/{aid}")[1]["balance"]


def txs(b, aid, **q):
    qs = "&".join(f"{k}={v}" for k, v in {"period": "custom", "from": "2000-01-01", **q}.items())
    return b.call("GET", f"/api/accounts/{aid}/transactions?{qs}")[1]["items"]


u1 = Browser().login("user1")
u1_nopin = Browser().login("user1", verify=False)
u2 = Browser().login("user2", verify=False)
u4 = Browser().login("user4")
anon = Browser()

# ───── ACC-01 · ACC-16 · 공통 ─────
s, body = anon.call("GET", "/api/products")
check("상품 안내는 로그인 없이 3종", s == 200 and [p["type"] for p in body["items"]] == ["checking", "deposit", "savings"])
check("미인증 계좌 목록 401", anon.call("GET", "/api/accounts")[0] == 401)
s, body = u1.call("GET", "/api/accounts")
check("ACC-04 user1 계좌 4개, 총 잔액 5,600,000원", s == 200 and len(body["items"]) == 4 and body["totalBalance"] == 5_600_000, body)
check("대표계좌가 맨 앞", body["items"][0]["accountId"] == 1 and body["items"][0]["isPrimary"])
s, body = u1.call("GET", "/api/accounts?purpose=card_payment")
check("카드 결제 계좌 후보는 저축예금만(1·2번)", [a["accountId"] for a in body["items"]] == [1, 2] and body["items"][0]["accountMasked"] == "****1234"
      and "accountNo" not in body["items"][0], body)
s, body = u1.call("GET", "/api/accounts/1")
check("상세에는 전체 계좌번호", body.get("accountNo") == "1002-123-451234")
check("AF-13 타인 계좌 상세는 404", code(u1.call("GET", "/api/accounts/5")) == "ACCOUNT_NOT_FOUND")
check("AF-13 타인 계좌 거래 내역도 404", u1.call("GET", "/api/accounts/5/transactions")[0] == 404)
check("AF-13 타인 계좌 입금도 404", u1.call("POST", "/api/accounts/5/deposit", {"amount": 1000})[0] == 404)
check("AF-13 존재하지 않는 계좌도 404", u1.call("GET", "/api/accounts/9999")[0] == 404)

# ───── 입금 ─────
s, body = u1.call("POST", "/api/accounts/2/deposit", {"amount": 100_000})
check("ACC-07 시연용 입금", s == 200 and body["balance"] == 600_000, body)
check("입금 거래는 ATM 입금으로 기록", txs(u1, 2)[0]["counterpartyName"] == "ATM 입금" and txs(u1, 2)[0]["direction"] == "in")
for bad in (0, -100, "abc", 1.5):
    check(f"AF-04 입금액 {bad!r} 거부", u1.call("POST", "/api/accounts/2/deposit", {"amount": bad})[0] == 400)
check("입금 1회 한도 초과", code(u1.call("POST", "/api/accounts/2/deposit", {"amount": 10_000_001})) == "DEPOSIT_LIMIT_EXCEEDED")
check("예금 계좌에는 입금 불가", code(u1.call("POST", "/api/accounts/3/deposit", {"amount": 1000})) == "ACCOUNT_STATE_INVALID")

# ───── 이체 ─────
T = {"fromAccountId": 2, "toAccountNo": "1002-123-459000", "amount": 10_000}
s, body = u1_nopin.call("POST", "/api/transfers", T)
check("AF-21 간편비밀번호 확인 없이 이체 403", s == 403 and body["code"] == "PIN_VERIFICATION_REQUIRED", body)
check("AF-21 잔액·거래 불변", bal(u1, 2) == 600_000 and bal(u2, 5) == 300_000 and len(txs(u2, 5)) == 2)
check("AF-01 잔액 부족", code(u1.call("POST", "/api/transfers", {**T, "amount": 700_000})) == "INSUFFICIENT_BALANCE")
check("AF-02 없는 계좌", code(u1.call("POST", "/api/transfers", {**T, "toAccountNo": "1002-123-000000"})) == "TRANSFER_TARGET_INVALID")
check("AF-06 예적금 계좌로 이체", code(u1.call("POST", "/api/transfers", {**T, "toAccountNo": "1002-223-460003"})) == "TRANSFER_TARGET_INVALID")
check("AF-03 같은 계좌로 이체", code(u1.call("POST", "/api/transfers", {**T, "toAccountNo": "1002-123-455678"})) == "SAME_ACCOUNT")
check("AF-03 같은 계좌(id)로 이체", code(u1.call("POST", "/api/transfers", {"fromAccountId": 2, "toAccountId": 2, "amount": 10})) == "SAME_ACCOUNT")
for bad in (0, -100, "abc"):
    check(f"AF-04 이체 금액 {bad!r} 거부", u1.call("POST", "/api/transfers", {**T, "amount": bad})[0] == 400)
check("AF-05 1회 한도 초과", code(u1.call("POST", "/api/transfers", {**T, "fromAccountId": 1, "amount": 6_000_000})) == "TRANSFER_LIMIT_PER_TX")
check("AF-14 남의 계좌를 출금 계좌로 지정하면 거부", u1.call("POST", "/api/transfers", {**T, "fromAccountId": 5})[0] == 404 and bal(u2, 5) == 300_000)
check("받는 계좌를 둘 다 주면 거부", u1.call("POST", "/api/transfers", {**T, "toAccountId": 1})[0] == 400)
s, body = u1.call("GET", "/api/transfers/recipient?accountNo=1002-123-459000")
check("ACC-10 예금주 확인", s == 200 and body["ownerName"] == "이두리" and body["accountMasked"] == "****9000", body)
check("예금주 확인: 예적금·없는 계좌는 이체 불가", code(u1.call("GET", "/api/transfers/recipient?accountNo=1002-223-460003")) == "TRANSFER_TARGET_INVALID")
s, body = u1.call("POST", "/api/transfers", {**T, "memo": "점심값"})
check("ACC-10 타인 계좌 이체", s == 200 and body["toOwnerName"] == "이두리" and body["balance"] == 590_000, body)
check("양쪽 잔액·거래 2건", bal(u2, 5) == 310_000 and txs(u1, 2)[0]["type"] == "transfer_out" and txs(u2, 5)[0]["type"] == "transfer_in"
      and txs(u2, 5)[0]["counterpartyName"] == "김하나" and txs(u2, 5)[0]["balanceAfter"] == 310_000)
s, body = u1.call("POST", "/api/transfers", {"fromAccountId": 2, "toAccountId": 1, "amount": 50_000})
check("ACC-09 내 계좌 간 이체", s == 200 and bal(u1, 1) == 1_550_000 and bal(u1, 2) == 540_000, body)

# AF-23: 1일 한도(10,000,000원). 잔액을 채우고 3,000,000원씩
u1.call("POST", "/api/accounts/1/deposit", {"amount": 10_000_000})
used = 10_000 + 50_000
ok = [u1.call("POST", "/api/transfers", {"fromAccountId": 1, "toAccountNo": "1002-123-459000", "amount": 3_000_000})[0] for _ in range(3)]
s, body = u1.call("POST", "/api/transfers", {"fromAccountId": 1, "toAccountNo": "1002-123-459000", "amount": 3_000_000})
check("AF-23 1일 한도 초과(4번째)", ok == [200, 200, 200] and body.get("code") == "TRANSFER_LIMIT_PER_DAY" and body["details"]["used"] == used + 9_000_000, (ok, body))
check("AF-23 거래 기록 없음", bal(u1, 1) == 1_550_000 + 10_000_000 - 9_000_000)

# ACC-11 최근·자주 쓰는 계좌
s, body = u1.call("GET", "/api/transfers/recent")
check("ACC-11 최근 이체 계좌", s == 200 and [r["accountMasked"] for r in body["items"]][:1] == ["****9000"] and len(body["items"]) <= 5, body)
s, fav = u1.call("POST", "/api/favorites", {"accountNo": "1002-123-459000"})
check("자주 쓰는 계좌 등록(이름 기본값은 예금주)", s == 201 and fav["displayName"] == "이두리", fav)
check("중복 등록은 같은 항목", u1.call("POST", "/api/favorites", {"accountNo": "1002-123-459000"})[1]["id"] == fav["id"])
check("예적금 번호는 등록 불가", code(u1.call("POST", "/api/favorites", {"accountNo": "1002-223-460003"})) == "TRANSFER_TARGET_INVALID")
check("목록에 보임", len(u1.call("GET", "/api/favorites")[1]["items"]) == 1)
check("타인은 내 즐겨찾기를 못 지움", u2.call("DELETE", f"/api/favorites/{fav['id']}")[0] == 404)
check("삭제", u1.call("DELETE", f"/api/favorites/{fav['id']}")[0] == 204 and u1.call("GET", "/api/favorites")[1]["items"] == [])

# ───── 거래 내역(ACC-06) ─────
check("출금 필터는 출금만", all(t["direction"] == "out" for t in txs(u1, 1, type="withdraw")) and txs(u1, 1, type="withdraw"))
check("입금 필터는 입금만", all(t["direction"] == "in" for t in txs(u1, 1, type="deposit")))
check("최신순", [t["createdAt"] for t in txs(u1, 1)] == sorted([t["createdAt"] for t in txs(u1, 1)], reverse=True))
check("기간이 거꾸로면 400", code(u1.call("GET", "/api/accounts/1/transactions?period=custom&from=2026-02-01&to=2026-01-01")) == "VALIDATION_FAILED")
s, body = u1.call("GET", "/api/accounts/1/transactions?period=custom&from=2020-01-01")
check("직접 입력 기간 + 페이지", s == 200 and body["page"] == 1 and len(body["items"]) <= 20, body)

# ───── 계좌 개설(ACC-02·03) ─────
s, acc = u2.call("POST", "/api/accounts", {"productType": "checking", "agreed": True, "alias": "여행"})
check("저축예금 개설", s == 201 and acc["balance"] == 0 and acc["isPrimary"] is False and acc["accountNo"].startswith("1002-123-"), acc)
check("개설 거래 open 0원", txs(u2, acc["accountId"])[0]["type"] == "open")
check("약관 미동의 거부", u2.call("POST", "/api/accounts", {"productType": "checking", "agreed": False})[0] == 400)
fillers = [u2.call("POST", "/api/accounts", {"productType": "checking", "agreed": True})[1]["accountId"] for _ in range(3)]
s, body = u2.call("POST", "/api/accounts", {"productType": "checking", "agreed": True})
check("저축예금 보유 한도 5개", s == 409 and body["code"] == "ACCOUNT_COUNT_LIMIT_EXCEEDED" and body["details"]["max"] == 5, body)
check("잔액 0원 저축예금은 받을 계좌 없이 바로 해지", u2.call("POST", f"/api/accounts/{fillers[0]}/close", {})[1].get("status") == "closed")
check("AF-10 예치금 잔액 부족", code(u2.call("POST", "/api/accounts", {"productType": "deposit", "agreed": True, "amount": 50_000_000, "termMonths": 12, "linkedAccountId": 5})) == "INSUFFICIENT_BALANCE")
check("AF-08 적금 중복 개설", code(u1.call("POST", "/api/accounts", {"productType": "savings", "agreed": True, "monthlyAmount": 100_000, "paymentDay": 10, "linkedAccountId": 1})) == "ACCOUNT_COUNT_LIMIT_EXCEEDED")
D = {"productType": "deposit", "agreed": True, "amount": 400_000, "termMonths": 6, "linkedAccountId": 1}
for label, patch in (("AF-09 예금 5,000원", {"amount": 5000}), ("AF-09 예금 기간 40개월", {"termMonths": 40}), ("예금 1억 초과", {"amount": 100_000_001}),
                     ("출금 계좌 없음", {"linkedAccountId": None}), ("타인 계좌를 출금 계좌로", {"linkedAccountId": 5})):
    s, body = u1.call("POST", "/api/accounts", {**D, **patch})
    check(label + " 거부", s in (400, 404), (s, body))
s, dep = u1.call("POST", "/api/accounts", D)
today = date.today()
check("정기예금 개설: 잔액·만기·금리", s == 201 and dep["balance"] == 400_000 and dep["rate"] == 2.9 and dep["maturityDate"] == add_months(today, 6).isoformat(), dep)
check("정기예금 개설: 출금 계좌 차감 + 거래 2건", bal(u1, 1) == 1_550_000 + 10_000_000 - 9_000_000 - 400_000 and txs(u1, 1)[0]["type"] == "transfer_out" and txs(u1, dep["accountId"])[0]["type"] == "transfer_in")
iid = dep["accountId"]
check("ACC-12 이자: 방금 가입이라 쌓인 이자 0, 만기 예상 이자 > 0", u1.call("GET", f"/api/accounts/{iid}/interest")[1]["accrued"] == 0 and u1.call("GET", f"/api/accounts/{iid}/interest")[1]["atMaturity"] > 0)
check("저축예금에는 이자 조회 불가", code(u1.call("GET", "/api/accounts/1/interest")) == "ACCOUNT_STATE_INVALID")

# AF-07: 저축예금이 없는 사용자(user4 가 유일한 저축예금을 해지)
check("user4 잔액을 이체", u4.call("POST", "/api/transfers", {"fromAccountId": 6, "toAccountNo": "1002-123-459000", "amount": 100_000})[0] == 200)
check("user4 저축예금 해지(잔액 0이라 바로)", u4.call("POST", "/api/accounts/6/close", {})[1].get("status") == "closed")
s, body = u4.call("POST", "/api/accounts", {"productType": "deposit", "agreed": True, "amount": 100_000, "termMonths": 6, "linkedAccountId": 6})
check("AF-07 저축예금 없이 예금 개설", code((s, body)) == "CHECKING_REQUIRED", body)
check("해지한 계좌는 해지된 계좌 목록에", [a["accountId"] for a in u4.call("GET", "/api/accounts?status=closed")[1]["items"]] == [6] and u4.call("GET", "/api/accounts")[1]["items"] == [])
check("해지된 계좌는 입금 불가", code(u4.call("POST", "/api/accounts/6/deposit", {"amount": 1000})) == "ACCOUNT_STATE_INVALID")

# ───── 적금 납입(ACC-08) ─────
s, sav = u1.call("GET", "/api/accounts/4")
check("적금 상세: 3회차 납입, 자동이체 켜짐", sav["paidCount"] == 3 and sav["autoPay"] is True and sav["balance"] == 600_000)
s, body = u1.call("POST", "/api/accounts/4/pay")
if sav["paidThisMonth"]:
    check("AF-11 이미 낸 달에 납입 거부", code((s, body)) == "SAVINGS_ALREADY_PAID", body)
else:
    check("수동 납입 4회차", s == 200 and body["paidCount"] == 4 and body["balance"] == 800_000, body)
    check("AF-11 이중 납입 거부", code(u1.call("POST", "/api/accounts/4/pay")) == "SAVINGS_ALREADY_PAID")
paid_now = u1.call("GET", "/api/accounts/4")[1]["paidCount"]
s, body = u1.call("POST", "/api/accounts/4/auto-pay", {"enabled": False})
check("자동이체 끄기", s == 200 and body["autoPay"] is False)
check("예금 계좌는 납입·자동이체 설정 불가", code(u1.call("POST", f"/api/accounts/{iid}/pay")) == "ACCOUNT_STATE_INVALID" and u1.call("POST", f"/api/accounts/{iid}/auto-pay", {"enabled": True})[0] == 409)

# ───── 해지 ─────
# AF-12 / AF-20
check("AF-12 연결된 예적금이 있는 저축예금 해지 거부", code(u1.call("POST", "/api/accounts/1/close", {})) == "ACCOUNT_LINKED_SAVINGS")
s, body = u1.call("GET", "/api/accounts/2/close-preview")
check("AF-20 카드 결제 계좌 해지 거부", code(u1.call("POST", "/api/accounts/2/close", {"receivingAccountId": 1})) == "ACCOUNT_LINKED_CARD"
      and body["blocker"]["code"] == "ACCOUNT_LINKED_CARD", body)
check("AF-20 계좌 상태·잔액 불변", u1.call("GET", "/api/accounts/2")[1]["status"] == "active" and bal(u1, 2) == 540_000)
# 저축예금 해지: 잔액 있으면 받을 계좌 필요, 간편비밀번호 없이도 가능
s, new = u2.call("POST", "/api/accounts", {"productType": "checking", "agreed": True})
check("해지 대상 저축예금 입금", u2.call("POST", f"/api/accounts/{new['accountId']}/deposit", {"amount": 5000})[0] == 200)
check("잔액이 있는데 받을 계좌가 없으면 거부", code(u2.call("POST", f"/api/accounts/{new['accountId']}/close", {})) == "CLOSE_TARGET_REQUIRED")
check("받을 계좌가 자기 자신이면 거부", code(u2.call("POST", f"/api/accounts/{new['accountId']}/close", {"receivingAccountId": new["accountId"]})) == "SAME_ACCOUNT")
check("타인 계좌로는 못 받음", u2.call("POST", f"/api/accounts/{new['accountId']}/close", {"receivingAccountId": 1})[0] == 404)
s, body = u2.call("POST", f"/api/accounts/{new['accountId']}/close", {"receivingAccountId": 5})
check("ACC-15 저축예금 해지(S-08 없이): 잔액 이전", s == 200 and body["status"] == "closed" and bal(u2, 5) == 310_000 + 9_000_000 + 100_000 + 5000, body)
s, body = u2.call("POST", "/api/accounts/5/close", {"receivingAccountId": acc["accountId"]})
check("대표계좌 해지 시 대표 이전", s == 200 and u2.call("GET", f"/api/accounts/{acc['accountId']}")[1]["isPrimary"] is True and bal(u2, acc["accountId"]) == 9_415_000, body)

# AF-16 / AF-22: 중도 해지
s, prev = u1.call("GET", "/api/accounts/3/close-preview")
days = (today - date.fromisoformat(prev["openedAt"])).days
check("AF-16 중도해지 금리 1.0% 로 계산", s == 200 and prev["kind"] == "early" and prev["appliedRate"] == 1.0 and prev["contractRate"] == 2.9
      and prev["interest"] == 3_000_000 * 100 * days // (365 * 10_000) and prev["total"] == 3_000_000 + prev["interest"], prev)
before = bal(u1, 1)
s, body = u1_nopin.call("POST", "/api/accounts/3/close", {})
check("AF-22 간편비밀번호 확인 없이 예적금 해지 403", s == 403 and body["code"] == "PIN_VERIFICATION_REQUIRED" and u1.call("GET", "/api/accounts/3")[1]["status"] == "active"
      and bal(u1, 1) == before, body)
s, body = u1.call("POST", "/api/accounts/3/close", {})
check("ACC-14 중도 해지: 원금+이자가 저축예금으로", s == 200 and body["status"] == "closed_early" and body["interest"] == prev["interest"]
      and bal(u1, 1) == before + 3_000_000 + prev["interest"] and bal(u1, 3) == 0, body)
t = txs(u1, 1)
check("해지 거래: 원금 입금 + 이자 interest 1건", t[0]["type"] == "interest" and t[0]["amount"] == prev["interest"] and t[1]["type"] == "transfer_in" and t[1]["amount"] == 3_000_000)
check("해지된 계좌에 close 0원", txs(u1, 3)[0]["type"] == "close" and txs(u1, 3)[0]["amount"] == 0)
check("이미 해지된 계좌 재해지 409", code(u1.call("POST", "/api/accounts/3/close", {})) == "ACCOUNT_STATE_INVALID")
check("타인의 예적금 해지는 404", u2.call("POST", "/api/accounts/4/close", {})[0] == 404)

# ACC-13: 만기 처리 (개발 모드 시뮬레이션)
s, body = u1.call("POST", "/api/dev/accounts/4/maturity")
check("만기 도래 시뮬레이션: 만기 안내 상태", s == 200 and body["isMatured"] is True and body["status"] == "active", body)
s, prev = u1.call("GET", "/api/accounts/4/close-preview")
check("만기 이후는 약정 금리 3.0%", prev["kind"] == "matured" and prev["appliedRate"] == 3.0 and prev["interest"] > 0, prev)
check("GET 조회만으로는 입금·상태 변경 없음", u1.call("GET", "/api/accounts/4")[1]["status"] == "active")
before = bal(u1, 1)
s, body = u1.call("POST", "/api/accounts/4/close", {"receivingAccountId": 2})
check("만기 해지: 지정한 저축예금으로 원리금", s == 200 and body["status"] == "matured" and bal(u1, 2) == 540_000 + body["total"] and bal(u1, 1) == before, body)

# ───── 자동이체 배치(AF-24~26)·롤백(AF-15): 서비스 함수를 직접 부른다 ─────
import os  # noqa: E402

if not os.getenv("DATABASE_URL"):
    print("SKIP 자동이체·롤백 시나리오: DATABASE_URL 을 서버와 같은 시험 DB 로 지정하세요")
else:
    from sqlalchemy import select  # noqa: E402

    from app import models as m  # noqa: E402
    from app.accounts import service as svc  # noqa: E402
    from app.db import SessionLocal  # noqa: E402

    # AF-15: 입금 기록 직전에 예외가 나면 출금도 롤백된다
    b1, b2 = bal(u1, 1), bal(u1, 2)
    with SessionLocal() as db:
        n_before = db.query(m.Transaction).count()
        orig, calls = svc._tx, []

        def boom(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("테스트용 오류")
            return orig(*a, **k)

        svc._tx = boom
        try:
            svc.transfer(db, db.get(m.User, 1), 1, 1000, to_account_id=2)
            failed = False
        except RuntimeError:
            failed = True
            db.rollback()
        finally:
            svc._tx = orig
    with SessionLocal() as db:
        check("AF-15 이체 중 오류: 양쪽 잔액 불변·거래 기록 없음", failed and db.query(m.Transaction).count() == n_before
              and db.get(m.Account, 1).balance == b1 and db.get(m.Account, 2).balance == b2)

    # 새 적금(자동이체)으로 배치 확인: user2 의 새 저축예금에서 출금
    s, sv = u2.call("POST", "/api/accounts", {"productType": "savings", "agreed": True, "monthlyAmount": 100_000, "paymentDay": 5,
                                              "linkedAccountId": acc["accountId"], "autoPay": True})
    sid, lid = sv["accountId"], acc["accountId"]
    check("정기적금 개설: 1회차 납입, 12개월 만기", s == 201 and sv["paidCount"] == 1 and sv["balance"] == 100_000 and sv["termMonths"] == 12 and sv["autoPay"] is True, sv)
    far = date.today() + timedelta(days=400)
    with SessionLocal() as db:  # AF-24: 잔액 부족이면 미납으로 두고 거래 기록이 없다
        saved = db.get(m.Account, lid).balance
        db.get(m.Account, lid).balance = 50_000
        db.commit()
        n = db.query(m.Transaction).count()
        paid = svc.run_auto_pay(db, today=date.today() + timedelta(days=31))
        check("AF-24 자동이체 잔액 부족: 납입 없음·거래 없음·미납 표시", paid == 0 and db.query(m.Transaction).count() == n
              and db.get(m.Account, sid).paid_count == 1 and u2.call("GET", f"/api/accounts/{sid}")[1]["paidCount"] == 1)
        db.get(m.Account, lid).balance = saved
        db.commit()
    with SessionLocal() as db:
        paid = svc.run_auto_pay(db, today=date.today() + timedelta(days=31))
        row = db.get(m.Account, sid)
        check("AF-24 잔액을 채우고 다시 실행하면 납입(이월 회차 포함)", paid >= 1 and row.paid_count == 1 + paid and row.balance == 100_000 * row.paid_count, (paid, row.paid_count))
        last = db.scalar(select(m.Transaction).where(m.Transaction.account_id == sid).order_by(m.Transaction.id.desc()))
        check("자동이체 표시명", last.counterparty_name.endswith("회차 자동이체"), last.counterparty_name)
    check("AF-25 자동이체된 달에 수동 납입 거부", code(u2.call("POST", f"/api/accounts/{sid}/pay")) == "SAVINGS_ALREADY_PAID")
    s, body = u2.call("POST", f"/api/accounts/{sid}/auto-pay", {"enabled": False})
    with SessionLocal() as db:  # AF-26
        before_count = db.get(m.Account, sid).paid_count
        check("AF-26 자동이체 끈 적금은 배치가 건드리지 않음", svc.run_auto_pay(db, today=far) == 0 and db.get(m.Account, sid).paid_count == before_count)
    s, body = u2.call("POST", "/api/dev/auto-pay/run")
    check("개발 모드 자동이체 실행 API", s == 200 and "paid" in body, body)

# ───── 가계부·홈 연동 ─────
s, body = u1.call("GET", "/api/home")
check("홈 요약이 새 계좌 구조로 동작", s == 200 and body["accounts"]["items"][0]["masked"] == "****1234", body)
s, body = u1.call("GET", "/api/ledger/summary")
check("가계부 요약: 대표계좌 ****1234", s == 200 and body["account"]["masked"] == "****1234", body)
s, body = u1.call("GET", "/api/ledger/income")
check("가계부 수입: 내 계좌 간 이체·해지 입금은 수입이 아님", s == 200 and all(i["source"] not in ("정기예금 중도해지", "생활비") for i in body["items"]), body)

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
