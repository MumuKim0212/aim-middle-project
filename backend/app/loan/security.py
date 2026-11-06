"""[역할] 보안 가드레일: 비밀키, 해시·마스킹, 개인정보 탐지, 요청 속도 제한, 안전한 로그."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque

from . import config
from .errors import RateLimited

# ---------------------------------------------------------------- 비밀키
def _load_secret() -> bytes:
    """환경변수 LOAN_SECRET_KEY 우선, 없으면 data/.secret_key를 만들어 씀(데모용)."""
    env = os.environ.get("LOAN_SECRET_KEY")
    if env:
        return env.encode()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config.SECRET_PATH.exists():
        config.SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(config.SECRET_PATH, 0o600)
        except OSError:
            pass
    return config.SECRET_PATH.read_text(encoding="utf-8").strip().encode()


_SECRET = _load_secret()


def keyed_hash(value: str) -> str:
    """식별정보(계좌번호·사번 등)는 원문 대신 HMAC-SHA256만 저장한다(조회용, 복원 불가)."""
    return hmac.new(_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- 마스킹
def mask_account(no: str) -> str:
    """계좌번호 가운데를 가림: 123-456789-01234 → 123-****89-***34."""
    digits = re.sub(r"\D", "", no)
    if len(digits) < 6:
        return "*" * len(no)
    parts = no.split("-")
    if len(parts) == 3:
        return f"{parts[0]}-****{parts[1][-2:]}-***{parts[2][-2:]}"
    return digits[:3] + "*" * (len(digits) - 5) + digits[-2:]


def mask_name(name: str) -> str:
    """이름 가운데 글자 가림: 김민수 → 김*수, 홍길 → 홍*."""
    name = name.strip()
    if len(name) <= 1:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


_PII_PATTERNS = [
    (re.compile(r"\b\d{6}-?[1-4]\d{6}\b"), "[주민번호]"),
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[전화번호]"),
    (re.compile(r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b"), "[카드번호]"),
    (re.compile(r"\b\d{3,6}-\d{4,6}-\d{3,7}\b"), "[계좌번호]"),   # 날짜(2026-11-05)는 걸리지 않게 가운데 4자리 이상
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[이메일]"),
]


def mask_pii(text: str) -> str:
    """LLM 전송·로그 기록 전에 개인정보 패턴을 토큰으로 치환한다."""
    for pat, token in _PII_PATTERNS:
        text = pat.sub(token, text)
    return text


def contains_pii(text: str) -> bool:
    return any(p.search(text) for p, _ in _PII_PATTERNS)


# ---------------------------------------------------------------- 속도 제한
class RateLimiter:
    """키(회원·출처)별 슬라이딩 윈도 속도 제한. 외부 조회 남용·무차별 대입을 막는다."""

    def __init__(self, limit: int = config.RATE_LIMIT_PER_MIN, window_sec: float = 60.0):
        self.limit, self.window = limit, window_sec
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise RateLimited(detail=f"rate limit {key}")
        q.append(now)


RATE_LIMITER = RateLimiter()


# ---------------------------------------------------------------- 안전한 로그
class _PiiFilter(logging.Filter):
    """모든 로그 메시지에서 개인정보 패턴을 지운다."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_pii(str(record.msg))
        if record.args:
            record.args = tuple(mask_pii(str(a)) for a in record.args)
        return True


def get_logger() -> logging.Logger:
    log = logging.getLogger("loan")
    if not log.handlers:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(config.LOG_PATH, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        h.addFilter(_PiiFilter())
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log
