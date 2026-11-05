"""로그인 보호 장치. 로그인 필요 API 는 전부 `user: User = Depends(current_user)` 하나로 막는다(기획서 6.1).

  · 미인증 → 401 LOGIN_REQUIRED, 30분 무활동 → 401 SESSION_EXPIRED
  · 간편비밀번호 미설정 세션 → 403 PIN_SETUP_REQUIRED (R10). 설정 API 만 current_user_any 로 이 검사를 건너뛴다.
  · 사용자는 요청마다 세션의 user_id 로 DB 에서 다시 읽는다(R6). 폼·URL 로 넘어온 user_id 는 쓰지 않는다(R3).
오류 응답은 {"code", "message", "details"?} 모양이다(공통.md 5장, common/오류코드.md).
"""
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db

SESSION_SECONDS = 30 * 60  # 마지막 활동 기준 30분(슬라이딩)
PIN_VERIFIED_SECONDS = 5 * 60  # 2차 인증 통과 후 5분 안에만 중요 동작 가능(R9)


def api_error(status: int, code: str, message: str, **details) -> HTTPException:
    """{ code, message, details? } 오류. 추가 값(remainingAttempts, until, fields)은 details 안에 둔다."""
    body: dict = {"code": code, "message": message}
    if details:
        body["details"] = details
    return HTTPException(status, body)


def validation_error(field: str, reason: str, message: str) -> HTTPException:
    """400 VALIDATION_FAILED, details.fields: [{ field, reason, message }] (오류코드.md 6절 reason)."""
    return api_error(400, "VALIDATION_FAILED", message, fields=[{"field": field, "reason": reason, "message": message}])


def _load(request: Request, db: Session, check_pin_setup: bool) -> m.User:
    uid = request.session.get("user_id")
    if not uid:
        raise api_error(401, "LOGIN_REQUIRED", "로그인이 필요합니다.")
    now = time.time()
    last = request.session.get("last_active")
    if last is None or now - last > SESSION_SECONDS:
        request.session.clear()
        raise api_error(401, "SESSION_EXPIRED", "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.")
    request.session["last_active"] = now
    user = db.get(m.User, uid)
    if user is None:
        request.session.clear()
        raise api_error(401, "LOGIN_REQUIRED", "로그인이 필요합니다.")
    if check_pin_setup and request.session.get("pin_setup_required"):
        raise api_error(403, "PIN_SETUP_REQUIRED", "간편비밀번호를 먼저 설정해 주세요.")
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    return _load(request, db, check_pin_setup=True)


def current_user_any(request: Request, db: Session = Depends(get_db)) -> m.User:
    """간편비밀번호 설정·로그아웃·내 정보처럼 설정 전에도 필요한 API 용."""
    return _load(request, db, check_pin_setup=False)


def pin_verified(request: Request) -> bool:
    """이체 등 중요 동작 직전에 계좌 파트가 부르는 함수. 2차 인증을 5분 안에 통과했으면 True.
    False 이면 업무 API 가 403 PIN_VERIFICATION_REQUIRED 로 응답한다(require_pin_verified 참고)."""
    t = request.session.get("pin_verified_at")
    return bool(t) and time.time() - t <= PIN_VERIFIED_SECONDS



def require_pin_verified(request: Request) -> None:
    """업무 API 가 실행 직전에 부른다. 5분 안에 2차 인증을 하지 않았으면 403 PIN_VERIFICATION_REQUIRED."""
    if not pin_verified(request):
        raise api_error(403, "PIN_VERIFICATION_REQUIRED", "간편비밀번호 확인이 필요합니다.")
