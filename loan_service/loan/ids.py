"""[역할] 팀 규칙(접두어+ULID)에 맞는 ID와 대출 계약·계좌 번호를 만든다."""
from __future__ import annotations

import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """시간순으로 정렬되는 26자 ULID(48bit 시간 + 80bit 난수)."""
    ms = int(time.time() * 1000)
    rnd = secrets.randbits(80)
    value = (ms << 80) | rnd
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    """예: new_id('lap') → 'lap_01J...' (VARCHAR(40) 이내)."""
    if not prefix.isalnum() or len(prefix) > 8:
        raise ValueError("prefix must be short alphanumeric")
    return f"{prefix}_{ulid()}"


def contract_no(refi: bool, year: int) -> str:
    """대출 LA-YYYY-NNNNNN / 대환 RA-YYYY-NNNNNN (양식 번호 LN/RF와 겹치지 않게)."""
    return f"{'RA' if refi else 'LA'}-{year}-{secrets.randbelow(900000) + 100000}"


def loan_account_no() -> str:
    """대출 계좌번호(3-6-5자리). 원문은 화면 표시용으로만 쓰고 DB에는 마스킹·해시만 저장."""
    return f"{secrets.randbelow(900) + 100}-{secrets.randbelow(900000) + 100000}-{secrets.randbelow(90000) + 10000}"
