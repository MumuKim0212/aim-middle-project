"""인증 API (기획서 5·6·8장).

  POST /api/auth/signup/validate   가입 단계별 검증      POST /api/auth/signup          가입 + 자동 로그인
  POST /api/auth/login             아이디·비밀번호 로그인  GET  /api/auth/device          이 브라우저의 간편 로그인 가능 여부
  POST /api/auth/pin/login         간편 로그인           POST /api/auth/pin/setup       간편비밀번호 설정·변경·재설정
  POST /api/auth/pin/verify        2차 인증(중요 동작 직전)  POST /api/auth/device/register|revoke  기기 등록·해제
  POST /api/auth/logout            로그아웃(POST 만)     GET  /api/auth/session         로그인 상태    GET /api/me  내 정보
"""
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from . import security, validators as v
from .deps import PIN_VERIFIED_SECONDS, api_error, current_user, current_user_any, validation_error

router = APIRouter(prefix="/api/auth", tags=["auth"])
me_router = APIRouter(prefix="/api", tags=["auth"])

KST = timezone(timedelta(hours=9))
DEVICE_COOKIE = "device_token"
DEVICE_DAYS = 90
LOGIN_FAIL_LIMIT = 5
LOGIN_LOCK_MINUTES = 10
PIN_FAIL_LIMIT = 5
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)  # 간편비밀번호 잠금: 시간 경과로 풀리지 않는다
GENERIC_LOGIN_FAIL = "아이디 또는 비밀번호가 올바르지 않습니다."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user_out(u: m.User) -> dict:
    return {"id": u.id, "loginId": u.login_id, "name": u.name}


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return name
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def _device_name(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    browser = "Edge" if "Edg/" in ua else "Chrome" if "Chrome" in ua else "Firefox" if "Firefox" in ua else "Safari" if "Safari" in ua else "브라우저"
    os_ = "Windows" if "Windows" in ua else "Mac" if "Mac OS" in ua else "Android" if "Android" in ua else "iOS" if ("iPhone" in ua or "iPad" in ua) else "기타"
    return f"{browser} · {os_}"


def _start_session(request: Request, user: m.User, method: str) -> None:
    """로그인 성공 시 세션을 비우고 새로 만든다(세션 고정 공격 방지)."""
    request.session.clear()
    now = time.time()
    pin_ok = bool(user.simple_pin_hash) and not (user.pin_locked_until and user.pin_locked_until > _now())
    request.session.update({"user_id": user.id, "login_at": now, "login_method": method, "last_active": now,
                            "pin_setup_required": not pin_ok})


def _device_from_cookie(request: Request, db: Session) -> m.Device | None:
    token = request.cookies.get(DEVICE_COOKIE)
    if not token:
        return None
    dev = db.scalar(select(m.Device).where(m.Device.token_hash == security.token_hash(token)))
    if dev is None or dev.revoked_at is not None or dev.expires_at <= _now():
        return None
    return dev


def _set_device_cookie(response: Response, token: str) -> None:
    response.set_cookie(DEVICE_COOKIE, token, max_age=DEVICE_DAYS * 86400, httponly=True, samesite="lax", secure=False, path="/")


def _issue_device(request: Request, response: Response, db: Session, user: m.User) -> None:
    """이 브라우저를 기기로 등록한다. 같은 브라우저의 기존 등록은 해제하고 새로 만든다."""
    old = _device_from_cookie(request, db)
    if old is not None:
        old.revoked_at = _now()
    token = security.new_device_token()
    db.add(m.Device(user_id=user.id, token_hash=security.token_hash(token), device_name=_device_name(request),
                    expires_at=_now() + timedelta(days=DEVICE_DAYS)))
    db.commit()
    _set_device_cookie(response, token)


# ───────────── 회원가입 ─────────────


class SignupStepIn(BaseModel):
    step: int
    data: dict


def _fail(field: str, reason: str, message: str):
    return validation_error(field, reason, message)


def _pw_reason(msg: str) -> str:
    """check_password 가 돌려준 문구를 오류코드.md 6절의 reason 으로 바꾼다."""
    return "CONTAINS_LOGIN_ID" if msg == v.MSG_PW_HAS_ID else "PASSWORD_RULE"


def _login_id_taken(db: Session, login_id: str) -> bool:
    return db.scalar(select(m.User.id).where(m.User.login_id == v.norm_login_id(login_id))) is not None


def _validate_step(db: Session, step: int, d: dict) -> None:
    if step == 1:
        if not (d.get("termsService") and d.get("termsPrivacy")):
            raise _fail("terms", "MUST_BE_TRUE", v.MSG_TERMS)
    elif step == 2:
        if msg := v.check_login_id(str(d.get("loginId", ""))):
            raise _fail("loginId", "INVALID_FORMAT", msg)
        if _login_id_taken(db, str(d["loginId"])):
            raise _fail("loginId", "ALREADY_TAKEN", v.MSG_ID_TAKEN)
    elif step == 3:
        pw, pw2 = str(d.get("password", "")), str(d.get("passwordConfirm", ""))
        if msg := v.check_password(pw, str(d.get("loginId", ""))):
            raise _fail("password", _pw_reason(msg), msg)
        if pw != pw2:
            raise _fail("passwordConfirm", "MISMATCH", v.MSG_PW_MISMATCH)
    elif step == 4:
        if msg := v.check_name(str(d.get("name", ""))):
            raise _fail("name", "INVALID_FORMAT", msg)
        if msg := v.check_birth(str(d.get("birthDate", ""))):
            raise _fail("birthDate", "UNDER_AGE" if msg == v.MSG_BIRTH_AGE else "INVALID_FORMAT", msg)
        if msg := v.check_phone(str(d.get("phone", ""))):
            raise _fail("phone", "INVALID_FORMAT", msg)
    else:
        raise _fail("step", "INVALID_ENUM", "알 수 없는 단계입니다.")


@router.post("/signup/validate")
def signup_validate(body: SignupStepIn, db: Session = Depends(get_db)):
    """'다음' 버튼을 눌렀을 때 그 단계를 서버에서 검증한다(아이디 중복 포함)."""
    _validate_step(db, body.step, body.data)
    return {"ok": True}


@router.post("/signup", status_code=201)
def signup(body: dict, request: Request, db: Session = Depends(get_db)):
    """5단계 입력값을 한 번에 받아 모두 다시 검증하고 저장한다. 성공하면 자동 로그인한다."""
    for step in (1, 2, 3, 4):
        _validate_step(db, step, body)
    user = m.User(
        login_id=v.norm_login_id(body["loginId"]), password_hash=security.hash_secret(body["password"]),
        name=str(body["name"]).strip(), birth_date=v.parse_birth(body["birthDate"]), phone=v.norm_phone(body["phone"]),
        marketing_agree=bool(body.get("marketing")), last_login_at=_now())
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # 동시에 같은 아이디로 가입한 경우
        db.rollback()
        raise _fail("loginId", "ALREADY_TAKEN", v.MSG_ID_TAKEN) from None
    _start_session(request, user, "password")
    return {"user": _user_out(user), "pinSetupRequired": True, "next": "/auth/pin/setup"}


# ───────────── 아이디·비밀번호 로그인 ─────────────


class LoginIn(BaseModel):
    loginId: str
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.login_id == v.norm_login_id(body.loginId)))
    if user is None:
        security.check_secret(body.password, security.hash_secret("dummy-password"))  # 응답 시간 차이로 아이디 유무가 드러나지 않게
        raise api_error(401, "INVALID_CREDENTIALS", GENERIC_LOGIN_FAIL)
    now = _now()
    if user.locked_until and user.locked_until <= now:  # 잠금이 풀렸으면 카운트를 새로 센다
        user.failed_login_count, user.locked_until = 0, None
    if user.locked_until and user.locked_until > now:
        hhmm = user.locked_until.astimezone(KST).strftime("%H:%M")
        raise api_error(423, "LOGIN_LOCKED", f"비밀번호를 5회 이상 잘못 입력해 10분간 로그인할 수 없습니다. ({hhmm} 이후 가능)",
                        until=user.locked_until.isoformat())
    if not security.check_secret(body.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= LOGIN_FAIL_LIMIT:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
        db.commit()
        raise api_error(401, "INVALID_CREDENTIALS", GENERIC_LOGIN_FAIL)
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    db.commit()
    _start_session(request, user, "password")
    dev = _device_from_cookie(request, db)
    needs_pin = bool(request.session["pin_setup_required"])
    return {"user": _user_out(user), "pinSetupRequired": needs_pin,
            "canRegisterDevice": (not needs_pin) and not (dev and dev.user_id == user.id)}


# ───────────── 간편 로그인 · 기기 ─────────────


@router.get("/device")
def device_info(request: Request, response: Response, db: Session = Depends(get_db)):
    """이 브라우저로 간편 로그인을 보여 줄지 정한다. 쿠키가 위조·만료면 지운다(F-17)."""
    dev = _device_from_cookie(request, db)
    user = db.get(m.User, dev.user_id) if dev else None
    if dev is None or user is None or not user.simple_pin_hash:
        if request.cookies.get(DEVICE_COOKIE):
            response.delete_cookie(DEVICE_COOKIE, path="/")
        return {"registered": False}
    pin_locked = bool(user.pin_locked_until and user.pin_locked_until > _now())
    return {"registered": True, "name": _mask_name(user.name), "pinLocked": pin_locked,
            "remaining": max(0, PIN_FAIL_LIMIT - user.pin_failed_count)}


class PinIn(BaseModel):
    pin: str


def _pin_format_ok(pin: str) -> bool:
    return pin.isascii() and pin.isdigit() and len(pin) == 6


def _bad_pin_response(db: Session, user: m.User, status: int = 403):
    """간편비밀번호가 틀렸을 때(간편 로그인·2차 인증 공용): 횟수를 올리고 5회면 잠근다.
    PIN_MISMATCH 의 HTTP 상태는 로그인 전 인증(/pin/login)이 401, 로그인 후 확인(/pin/verify, /pin/setup)이 403이다."""
    user.pin_failed_count += 1
    if user.pin_failed_count >= PIN_FAIL_LIMIT:
        user.pin_locked_until = FAR_FUTURE
        db.commit()
        return api_error(423, "PIN_LOCKED", "간편비밀번호가 잠겼습니다. 아이디와 비밀번호로 로그인해 주세요.")
    db.commit()
    left = PIN_FAIL_LIMIT - user.pin_failed_count
    return api_error(status, "PIN_MISMATCH", f"간편비밀번호가 틀렸습니다. 남은 횟수 {left}회", remainingAttempts=left)


@router.post("/pin/login")
def pin_login(body: PinIn, request: Request, response: Response, db: Session = Depends(get_db)):
    dev = _device_from_cookie(request, db)
    user = db.get(m.User, dev.user_id) if dev else None
    if dev is None or user is None or not user.simple_pin_hash:
        response.delete_cookie(DEVICE_COOKIE, path="/")
        raise api_error(401, "DEVICE_INVALID", "등록된 기기가 아닙니다. 아이디와 비밀번호로 로그인해 주세요.")
    if user.pin_locked_until and user.pin_locked_until > _now():
        raise api_error(423, "PIN_LOCKED", "간편비밀번호가 잠겼습니다. 아이디와 비밀번호로 로그인해 주세요.")
    if not _pin_format_ok(body.pin):  # 형식 오류는 틀린 횟수에 넣지 않는다(5.4)
        raise validation_error("pin", "INVALID_FORMAT", "숫자 6자리를 입력해 주세요.")
    if not security.check_secret(body.pin, user.simple_pin_hash):
        raise _bad_pin_response(db, user, 401)
    now = _now()
    user.pin_failed_count, user.last_login_at = 0, now
    dev.last_used_at, dev.expires_at = now, now + timedelta(days=DEVICE_DAYS)  # 슬라이딩 90일
    db.commit()
    _start_session(request, user, "pin")
    token = request.cookies.get(DEVICE_COOKIE)
    if token:
        _set_device_cookie(response, token)
    return {"user": _user_out(user), "pinSetupRequired": False}


@router.post("/device/register")
def device_register(request: Request, response: Response, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """'이 기기에서 간편 로그인을 사용할까요?'에 '예'라고 한 경우."""
    if not user.simple_pin_hash:
        raise api_error(403, "PIN_SETUP_REQUIRED", "간편비밀번호를 먼저 설정해 주세요.")
    _issue_device(request, response, db, user)
    return {"ok": True}


@router.post("/device/revoke")
def device_revoke(request: Request, response: Response, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    dev = _device_from_cookie(request, db)
    if dev is not None and dev.user_id == user.id:
        dev.revoked_at = _now()
        db.commit()
    response.delete_cookie(DEVICE_COOKIE, path="/")
    return {"ok": True}


# ───────────── 간편비밀번호 설정 · 2차 인증 ─────────────


class PinSetupIn(BaseModel):
    pin: str
    pinConfirm: str
    currentPin: str | None = None  # 변경: 현재 6자리
    currentPassword: str | None = None  # 재설정: 현재 비밀번호


@router.post("/pin/setup")
def pin_setup(body: PinSetupIn, request: Request, response: Response, user: m.User = Depends(current_user_any),
              db: Session = Depends(get_db)):
    first_time = bool(request.session.get("pin_setup_required"))  # 가입 직후·미설정·잠김 → 건너뛸 수 없는 설정
    if not first_time and user.simple_pin_hash:  # 이미 쓰는 사람이 바꾸려면 현재 값을 먼저 확인
        if user.pin_locked_until and user.pin_locked_until > _now():
            raise api_error(423, "PIN_LOCKED", "간편비밀번호가 잠겼습니다. 아이디와 비밀번호로 다시 로그인해 주세요.")
        if body.currentPin is not None:
            if not _pin_format_ok(body.currentPin):
                raise validation_error("currentPin", "INVALID_FORMAT", "숫자 6자리를 입력해 주세요.")
            if not security.check_secret(body.currentPin, user.simple_pin_hash):
                raise _bad_pin_response(db, user)
        elif body.currentPassword is None:
            raise validation_error("currentPin", "REQUIRED", "현재 간편비밀번호를 입력해 주세요.")
        elif not security.check_secret(body.currentPassword, user.password_hash):
            raise api_error(403, "CURRENT_PASSWORD_INVALID", "현재 비밀번호가 올바르지 않습니다.")
    if not _pin_format_ok(body.pin):
        raise validation_error("pin", "INVALID_FORMAT", "숫자 6자리를 입력해 주세요.")
    if body.pin != body.pinConfirm:
        raise validation_error("pinConfirm", "MISMATCH", "두 번 입력한 번호가 다릅니다.")
    if v.weak_pin(body.pin, user.birth_date):
        raise validation_error("pin", "PIN_TOO_SIMPLE", "사용할 수 없는 번호입니다.")
    user.simple_pin_hash = security.hash_secret(body.pin)
    user.pin_set_at, user.pin_failed_count, user.pin_locked_until = _now(), 0, None
    db.commit()
    request.session["pin_setup_required"] = False
    _issue_device(request, response, db, user)  # 설정이 끝나면 이 브라우저를 기기로 등록한다
    return {"ok": True}


@router.post("/pin/verify")
def pin_verify(body: PinIn, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """이체 등 중요 동작 직전 2차 인증. 로그인에 쓰는 6자리를 그대로 쓰고, 틀린 횟수도 같이 센다(R9)."""
    if not user.simple_pin_hash:
        raise api_error(403, "PIN_SETUP_REQUIRED", "간편비밀번호를 먼저 설정해 주세요.")
    if user.pin_locked_until and user.pin_locked_until > _now():
        raise api_error(423, "PIN_LOCKED", "간편비밀번호가 잠겼습니다. 아이디와 비밀번호로 다시 로그인해 주세요.")
    if not _pin_format_ok(body.pin):  # 형식 오류는 틀린 횟수에 넣지 않는다(5.4)
        raise validation_error("pin", "INVALID_FORMAT", "숫자 6자리를 입력해 주세요.")
    if not security.check_secret(body.pin, user.simple_pin_hash):
        raise _bad_pin_response(db, user)
    user.pin_failed_count = 0
    db.commit()
    request.session["pin_verified_at"] = time.time()
    return {"verified": True, "validForSeconds": PIN_VERIFIED_SECONDS}


# ───────────── 비밀번호 변경 (AUTH-07) ─────────────


class PasswordChangeIn(BaseModel):
    currentPassword: str
    newPassword: str
    newPasswordConfirm: str
    revokeOtherDevices: bool = False  # 기본 "아니오"(단일 기기 전제)


@router.post("/password/change")
def password_change(body: PasswordChangeIn, request: Request, user: m.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """현재 비밀번호를 확인한 뒤 새 비밀번호로 바꾼다. 현재 비밀번호를 틀리면 로그인 실패와 같이 센다(5회 → 10분 잠금)."""
    now = _now()
    if user.locked_until and user.locked_until > now:
        hhmm = user.locked_until.astimezone(KST).strftime("%H:%M")
        raise api_error(423, "LOGIN_LOCKED", f"비밀번호를 5회 이상 잘못 입력해 잠겼습니다. ({hhmm} 이후 가능)",
                        until=user.locked_until.isoformat())
    if not security.check_secret(body.currentPassword, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= LOGIN_FAIL_LIMIT:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
        db.commit()
        raise api_error(403, "CURRENT_PASSWORD_INVALID", "현재 비밀번호가 올바르지 않습니다.")
    if msg := v.check_password(body.newPassword, user.login_id):
        raise _fail("newPassword", _pw_reason(msg), msg)
    if body.newPassword != body.newPasswordConfirm:
        raise _fail("newPasswordConfirm", "MISMATCH", v.MSG_PW_MISMATCH)
    if security.check_secret(body.newPassword, user.password_hash):
        raise _fail("newPassword", "SAME_AS_CURRENT", "현재 비밀번호와 같은 비밀번호는 사용할 수 없습니다.")
    user.password_hash = security.hash_secret(body.newPassword)
    user.failed_login_count, user.locked_until = 0, None
    if body.revokeOtherDevices:  # 이 브라우저의 등록만 남기고 나머지 기기 등록을 해제
        mine = _device_from_cookie(request, db)
        for d in db.scalars(select(m.Device).where(m.Device.user_id == user.id, m.Device.revoked_at.is_(None))):
            if mine is None or d.id != mine.id:
                d.revoked_at = now
    db.commit()
    return {"ok": True}


# ───────────── 로그아웃 · 세션 · 내 정보 ─────────────


@router.post("/logout")
def logout(request: Request):
    """세션만 끊는다(기기 쿠키는 유지). 로그인하지 않은 상태에서도 오류 없이 끝난다."""
    request.session.clear()
    return {"ok": True}


@router.get("/session")
def session_state(request: Request, db: Session = Depends(get_db)):
    """화면이 시작할 때 로그인 상태를 묻는다. 만료된 세션은 비운다."""
    uid = request.session.get("user_id")
    if uid:
        last = request.session.get("last_active")
        if last is None or time.time() - last > 30 * 60:
            request.session.clear()
            return {"authenticated": False, "expired": True}
        user = db.get(m.User, uid)
        if user is not None:
            request.session["last_active"] = time.time()
            return {"authenticated": True, "pinSetupRequired": bool(request.session.get("pin_setup_required")),
                    "user": _user_out(user)}
        request.session.clear()
    return {"authenticated": False}


@me_router.get("/me")
def me(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    dev = _device_from_cookie(request, db)
    mine = bool(dev and dev.user_id == user.id)
    return {"user": {**_user_out(user), "birthDate": user.birth_date.isoformat(), "phone": user.phone,
                     "createdAt": user.created_at.isoformat(),
                     "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None},
            "deviceRegistered": mine, "deviceName": dev.device_name if mine else None}


class PhoneChangeIn(BaseModel):
    phone: str


@me_router.post("/me/phone")
def change_phone(body: PhoneChangeIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """휴대폰 번호만 바꾼다(AUTH-06). 대상은 세션의 사용자뿐이고 요청 본문의 user_id 는 보지 않는다(R3)."""
    if msg := v.check_phone(body.phone):
        raise _fail("phone", "INVALID_FORMAT", msg)
    user.phone = v.norm_phone(body.phone)
    db.commit()
    return {"phone": user.phone}


def get_age(user: m.User, today: date | None = None) -> int:
    """생년월일 기반 나이 계산(계좌 파트의 상품 가입 조건용)."""
    return v.age_on(user.birth_date, today or date.today())
