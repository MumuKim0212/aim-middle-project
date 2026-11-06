"""[역할] 입력값 검증 가드레일: 타입·범위·허용 목록·길이·제어문자를 검사해 잘못된 값이 로직에 들어오지 못하게 한다."""
from __future__ import annotations

import re
import unicodedata

from .errors import LimitExceeded, ValidationError

JOBS = ("급여소득자", "개인사업자", "프리랜서", "연금소득자")
RATE_PREFS = ("고정금리", "변동금리", "혼합형", "상관없음")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_MARKUP = re.compile(r"[<>{}`]")          # 화면·로그에 태그/스크립트가 섞이지 않도록 차단


def clean_text(value: str, field: str, max_len: int = 50) -> str:
    """제어문자 제거·정규화·길이 제한(로그 주입·화면 깨짐 방지)."""
    if not isinstance(value, str):
        raise ValidationError(f"{field}은(는) 문자로 입력해 주세요.")
    v = unicodedata.normalize("NFC", _CTRL.sub("", value)).strip()
    if not v or len(v) > max_len:
        raise ValidationError(f"{field}은(는) 1~{max_len}자로 입력해 주세요.")
    if _MARKUP.search(v):
        raise ValidationError(f"{field}에 사용할 수 없는 문자(< > {{ }} `)가 있습니다.")
    return v


def int_range(value, field: str, lo: int, hi: int) -> int:
    """정수 변환 + 범위 검사. 문자열의 쉼표는 허용."""
    try:
        v = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{field}은(는) 숫자로 입력해 주세요.") from None
    if not lo <= v <= hi:
        raise ValidationError(f"{field}은(는) {lo:,} ~ {hi:,} 사이로 입력해 주세요.")
    return v


def choice(value: str, field: str, options) -> str:
    if value not in options:
        raise ValidationError(f"{field}은(는) {', '.join(map(str, options))} 중에서 골라 주세요.")
    return value


def desired_amount(amount: int, product) -> int:
    """희망 금액: 상품 최소~최대. 최대를 넘으면 '한도금액을 초과하였습니다.'(main 3.5)."""
    if amount > product["max_amount"]:
        raise LimitExceeded(f"한도금액을 초과하였습니다. 이 상품의 최대 한도는 {product['max_amount']:,}원입니다.")
    if amount < product["min_amount"]:
        raise ValidationError(f"희망 금액은 최소 {product['min_amount']:,}원 이상이어야 합니다.")
    return amount


def employee_no(value: str) -> str:
    v = clean_text(value, "사번", 20)
    if not re.fullmatch(r"[A-Za-z0-9-]{3,20}", v):
        raise ValidationError("사번은 영문·숫자 3~20자로 입력해 주세요.")
    return v
