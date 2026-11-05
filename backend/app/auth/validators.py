"""회원가입 입력 검증(기획서 4.1·4.2). 최종 판단은 항상 서버가 한다."""
import re
from datetime import date

# 필드 → 오류 메시지(기획서 4.1 표 그대로)
MSG_ID_FORMAT = "아이디는 영문 소문자와 숫자로 5~20자여야 합니다."
MSG_ID_TAKEN = "이미 사용 중인 아이디입니다."
MSG_PW_RULE = "비밀번호는 8~20자, 영문·숫자·특수문자 중 2종류 이상을 포함해야 합니다."
MSG_PW_HAS_ID = "아이디를 포함한 비밀번호는 사용할 수 없습니다."
MSG_PW_MISMATCH = "비밀번호가 일치하지 않습니다."
MSG_NAME = "이름을 정확히 입력해 주세요."
MSG_BIRTH_FORMAT = "생년월일 형식이 올바르지 않습니다."
MSG_BIRTH_AGE = "만 14세 이상만 가입할 수 있습니다."
MSG_PHONE = "휴대폰 번호를 정확히 입력해 주세요."
MSG_TERMS = "필수 약관에 동의해 주세요."

_ID = re.compile(r"^[a-z][a-z0-9]{4,19}$")
_NAME = re.compile(r"^(?:[가-힣]{2,10}|[A-Za-z]{2,30})$")


def norm_login_id(v: str) -> str:
    return (v or "").strip().lower()


def check_login_id(v: str) -> str | None:
    return None if _ID.match(norm_login_id(v)) else MSG_ID_FORMAT


def check_password(pw: str, login_id: str) -> str | None:
    pw = pw or ""
    if not 8 <= len(pw) <= 20:
        return MSG_PW_RULE
    kinds = sum(bool(x) for x in (re.search(r"[A-Za-z]", pw), re.search(r"\d", pw), re.search(r"[^A-Za-z0-9]", pw)))
    if kinds < 2 or re.search(r"(.)\1\1\1", pw):  # 같은 문자 4회 이상 연속 불가
        return MSG_PW_RULE
    lid = norm_login_id(login_id)
    if lid and (pw.lower() == lid or lid in pw.lower()):
        return MSG_PW_HAS_ID
    return None


def check_name(v: str) -> str | None:
    return None if _NAME.match((v or "").strip()) else MSG_NAME


def parse_birth(v: str) -> date | None:
    try:
        return date.fromisoformat((v or "").strip())
    except ValueError:
        return None


def age_on(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def check_birth(v: str, today: date | None = None) -> str | None:
    today = today or date.today()
    b = parse_birth(v)
    if b is None or b >= today:
        return MSG_BIRTH_FORMAT
    return None if age_on(b, today) >= 14 else MSG_BIRTH_AGE


def norm_phone(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def check_phone(v: str) -> str | None:
    p = norm_phone(v)
    return None if re.fullmatch(r"010\d{7,8}", p) else MSG_PHONE


def weak_pin(pin: str, birth: date | None) -> bool:
    """같은 숫자 6개, 연속 숫자(오름·내림), 생년월일 6자리(YYMMDD)는 약한 간편비밀번호로 본다."""
    if len(set(pin)) == 1:
        return True
    d = [int(c) for c in pin]
    if all(d[i + 1] - d[i] == 1 for i in range(5)) or all(d[i] - d[i + 1] == 1 for i in range(5)):
        return True
    return bool(birth and pin == birth.strftime("%y%m%d"))
