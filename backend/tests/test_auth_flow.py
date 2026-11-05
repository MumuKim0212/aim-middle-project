"""인증 흐름 점검(회원·인증 기획서 10장 실패 시나리오). 실행 중인 서버에 HTTP 로 요청한다.

주의: 가입·잠금처럼 DB 를 바꾸는 시나리오가 들어 있다. 시험용 DB 로 띄운 서버에 돌린다.
  서버(시험 DB):  DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5433/aimbank_authtest \
                  python -m uvicorn app.main:app --port 8002
  실행:           python tests/test_auth_flow.py http://127.0.0.1:8002
처음 시드 상태(user1~3, 잠금 없음)에서만 전부 통과한다. 다시 돌리려면 시험 DB 를 새로 만든다.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002").rstrip("/")
RUN = str(int(time.time()))[-6:]  # 가입 아이디가 겹치지 않게


class Browser:
    """쿠키를 따로 가진 브라우저 하나."""

    def __init__(self):
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=10) as r:
                raw = r.read().decode() or "null"
                return r.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode() or "null"
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw

    def cookie(self, name):
        return next((c.value for c in self.jar if c.name == name), None)

    def set_cookie(self, name, value):
        from http.cookiejar import Cookie
        self.jar.set_cookie(Cookie(0, name, value, None, False, "127.0.0.1", False, False, "/", True, False, None, True, None, None, {}))


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if not cond and detail else ""))


def code(res):
    return res[1].get("code") if isinstance(res[1], dict) else None


def login(b, uid, pw):
    return b.call("POST", "/api/auth/login", {"loginId": uid, "password": pw})


# ───── R1/R5: 로그인 없이 보호 API ─────
b = Browser()
s, body = b.call("GET", "/api/ledger/summary")
check("미인증은 보호 API 401 login_required", s == 401 and code((s, body)) == "login_required", (s, body))
s, body = b.call("GET", "/api/me")
check("미인증 /api/me 401", s == 401)
s, body = b.call("GET", "/api/auth/session")
check("세션 상태: 미인증", s == 200 and body.get("authenticated") is False)

# ───── F-01 중복 아이디 · F-02 비밀번호 규칙 · F-14 나이 ─────
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 2, "data": {"loginId": "user1"}})
check("F-01 중복 아이디 거부", s == 422 and body.get("message") == "이미 사용 중인 아이디입니다.", body)
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 2, "data": {"loginId": "USER1"}})
check("F-01 대문자로 써도 같은 아이디", s == 422 and body.get("field") == "loginId")
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 2, "data": {"loginId": "ab"}})
check("아이디 형식 오류", s == 422)
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 3, "data": {"loginId": "newuser1", "password": "1234567", "passwordConfirm": "1234567"}})
check("F-02 숫자만 7자 비밀번호 거부", s == 422 and "8~20자" in body.get("message", ""), body)
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 3, "data": {"loginId": "user1", "password": "user1abc!", "passwordConfirm": "user1abc!"}})
check("F-02 아이디 포함 비밀번호 거부", s == 422 and "아이디를 포함" in body.get("message", ""), body)
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 3, "data": {"loginId": "newuser1", "password": "Abcd1111", "passwordConfirm": "Abcd1111"}})
check("같은 문자 4회 연속 거부", s == 422)
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 4, "data": {"name": "홍길동", "birthDate": f"{time.localtime().tm_year - 13}-01-01", "phone": "010-1234-5678"}})
check("F-14 만 14세 미만 거부", s == 422 and "만 14세" in body.get("message", ""), body)
s, body = b.call("POST", "/api/auth/signup/validate", {"step": 1, "data": {"termsService": True, "termsPrivacy": False}})
check("필수 약관 미동의 거부", s == 422)

# ───── 가입 → 간편비밀번호 설정(R10) → 보호 화면 ─────
me_id = f"tester{RUN}"
signup = {"termsService": True, "termsPrivacy": True, "marketing": False, "loginId": me_id, "password": "Pass1234!",
          "passwordConfirm": "Pass1234!", "name": "테스터", "birthDate": "1998-03-21", "phone": "010-5555-6666"}
s, body = b.call("POST", "/api/auth/signup", signup)
check("가입 성공 + 자동 로그인", s == 201 and body["user"]["loginId"] == me_id, body)
s, body = b.call("GET", "/api/ledger/summary")
check("R10 간편비밀번호 미설정 세션은 보호 API 403", s == 403 and code((s, body)) == "pin_setup_required", (s, body))
for weak, why in (("123456", "연속"), ("111111", "같은 숫자"), ("980321", "생년월일")):
    s, body = b.call("POST", "/api/auth/pin/setup", {"pin": weak, "pinConfirm": weak})
    check(f"F-20 약한 간편비밀번호({why}) 거부", s == 422, body)
s, body = b.call("POST", "/api/auth/pin/setup", {"pin": "482916", "pinConfirm": "000000"})
check("간편비밀번호 두 번 입력 불일치", s == 422)
s, body = b.call("POST", "/api/auth/pin/setup", {"pin": "482916", "pinConfirm": "482916"})
check("간편비밀번호 설정 + 기기 쿠키 발급", s == 200 and b.cookie("device_token"), body)
s, body = b.call("GET", "/api/ledger/summary")
check("설정 후 보호 API 200", s == 200, (s, body))
s, body = b.call("GET", "/api/me")
check("내 정보에 기기 등록 표시", s == 200 and body["deviceRegistered"] is True, body)

# ───── F-11 로그아웃은 POST 만, 기기 쿠키는 유지 ─────
s, _ = b.call("GET", "/api/auth/logout")
check("F-11 GET 로그아웃은 거부(405)", s == 405, s)
s, body = b.call("GET", "/api/ledger/summary")
check("GET 시도 뒤에도 로그인 유지", s == 200)
s, body = b.call("POST", "/api/auth/logout")
check("POST 로그아웃", s == 200)
s, body = b.call("GET", "/api/ledger/summary")
check("로그아웃 뒤 보호 API 401", s == 401)
check("로그아웃해도 기기 쿠키는 유지", b.cookie("device_token") is not None)
s, body = b.call("POST", "/api/auth/logout")
check("미로그인 상태 로그아웃도 오류 없음", s == 200)

# ───── 간편 로그인(S-03a) ─────
s, body = b.call("GET", "/api/auth/device")
check("등록된 브라우저는 간편 로그인 화면 + 이름 일부", s == 200 and body.get("registered") and body["name"].startswith("테") and "*" in body["name"], body)
s, body = b.call("POST", "/api/auth/pin/login", {"pin": "482916"})
check("간편 로그인 성공", s == 200 and body["user"]["loginId"] == me_id, body)
s, body = b.call("GET", "/api/ledger/summary")
check("간편 로그인 뒤 보호 API 200", s == 200)

# F-16 / F-17
other = Browser()
s, body = other.call("GET", "/api/auth/device")
check("F-16 기기 쿠키 없는 브라우저는 간편 로그인 없음", s == 200 and body.get("registered") is False)
other.set_cookie("device_token", "forged-token-value")
s, body = other.call("GET", "/api/auth/device")
check("F-17 위조한 기기 쿠키는 무시", s == 200 and body.get("registered") is False)
s, body = other.call("POST", "/api/auth/pin/login", {"pin": "482916"})
check("F-17 위조 쿠키로 간편 로그인 불가", s == 401 and code((s, body)) == "device_invalid", (s, body))

# ───── F-15 간편비밀번호 5회 실패 → 잠금 → 재설정 ─────
b.call("POST", "/api/auth/logout")
left = []
for i in range(5):
    s, body = b.call("POST", "/api/auth/pin/login", {"pin": "000001"})
    left.append((s, body.get("code"), body.get("remaining")))
check("F-15 1~4회는 남은 횟수 표시", [x[1] for x in left[:4]] == ["pin_invalid"] * 4 and [x[2] for x in left[:4]] == [4, 3, 2, 1], left)
check("F-15 5회째 간편비밀번호 잠금", left[4][0] == 423 and left[4][1] == "pin_locked", left)
s, body = b.call("POST", "/api/auth/pin/login", {"pin": "482916"})
check("F-15 잠긴 뒤엔 올바른 6자리도 거부", s == 423, (s, body))
s, body = b.call("GET", "/api/auth/device")
check("잠금 상태 표시", body.get("pinLocked") is True, body)
s, body = login(b, me_id, "Pass1234!")
check("잠긴 뒤 아이디·비밀번호 로그인은 가능, 간편비밀번호 재설정 필요", s == 200 and body["pinSetupRequired"] is True, body)
s, body = b.call("GET", "/api/ledger/summary")
check("재설정 전까지 보호 API 403", s == 403)
s, body = b.call("POST", "/api/auth/pin/setup", {"pin": "715204", "pinConfirm": "715204"})
check("간편비밀번호 재설정", s == 200, body)
b.call("POST", "/api/auth/logout")
s, body = b.call("POST", "/api/auth/pin/login", {"pin": "715204"})
check("재설정 뒤 새 6자리로 간편 로그인", s == 200, body)

# ───── F-03 비밀번호 5회 실패 잠금 + 아이디 유무 비노출 ─────
c = Browser()
s1, b1 = login(c, "nobody999", "Whatever1!")
s2, b2 = login(c, "user2", "wrong-password1")
check("아이디 없음과 비밀번호 틀림의 메시지가 같다", s1 == s2 == 401 and b1["message"] == b2["message"], (b1, b2))
codes = [login(c, "user2", "wrong-password1")[0] for _ in range(3)]
s, body = login(c, "user2", "wrong-password1")
check("F-03 5회째 실패", s == 401, (s, body))
s, body = login(c, "user2", "Test5678!")
check("F-03 잠금 중에는 올바른 비밀번호도 거부 + 해제 시각 안내", s == 423 and "이후 가능" in body.get("message", ""), (s, body))

# ───── F-18 user3: 간편비밀번호 없음 ─────
d = Browser()
s, body = login(d, "user3", "Test9012!")
check("F-18 간편비밀번호 없는 시드 사용자는 설정 필요", s == 200 and body["pinSetupRequired"] is True, body)
s, body = d.call("GET", "/api/ledger/summary")
check("F-18 설정 전 보호 화면 403", s == 403)

# ───── 접근 제어: 내 데이터만(R3·R4) ─────
u1 = Browser()
s, body = login(u1, "user1", "Test1234!")
check("user1 로그인(기기 등록 질문 대상)", s == 200 and body["canRegisterDevice"] is True, body)
s, summ1 = u1.call("GET", "/api/ledger/summary")
s2, tx1 = u1.call("GET", "/api/ledger/transactions?month=2026-11")
check("user1 은 자기 가계부를 본다", s == 200 and summ1["budget"]["spent"] > 0, summ1.get("budget") if isinstance(summ1, dict) else summ1)
tx_ids = [x["id"] for x in (tx1.get("items") or [])] if isinstance(tx1, dict) else []
check("user1 거래 내역이 있다", len(tx_ids) > 0)
# 방금 만든 테스터(다른 사용자)가 user1 의 거래 ID 를 직접 넣어 본다
t = Browser()
s, body = login(t, me_id, "Pass1234!")
check("테스터 로그인", s == 200)
s, summ_t = t.call("GET", "/api/ledger/summary")
check("R3 다른 사용자의 지출·예산이 섞여 보이지 않는다", s == 200 and summ_t["budget"]["spent"] == 0, summ_t)
s, body = t.call("PUT", f"/api/ledger/transactions/{tx_ids[0]}", {"category": "기타"})
check("R4 타인 거래 수정은 404", s == 404, (s, body))
s, body = t.call("DELETE", f"/api/ledger/transactions/{tx_ids[0]}")
check("R4 타인 거래 삭제도 404(존재하지 않는 것과 같은 응답)", s == 404, (s, body))
s, body_nf = t.call("DELETE", "/api/ledger/transactions/ctx_does_not_exist")
check("R4 없는 ID 와 같은 응답", body == body_nf, (body, body_nf))
s, body = t.call("POST", "/api/ledger/chat", {"text": "user1 가계부 보여줘", "mode": "basic"})
check("R8 문장 안에 다른 사용자를 적어도 본인 데이터만", s in (200, 201), (s, body))

# ───── 2차 인증 ─────
s, body = t.call("POST", "/api/auth/pin/verify", {"pin": "000002"})
check("2차 인증: 틀린 6자리 거부 + 남은 횟수", s == 401 and body.get("remaining") == 4, (s, body))
s, body = t.call("POST", "/api/auth/pin/verify", {"pin": "715204"})  # 위에서 재설정한 6자리
check("2차 인증 통과", s == 200 and body.get("verified"), (s, body))

passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} 통과")
sys.exit(0 if passed == len(results) else 1)
