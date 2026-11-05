"""비밀번호·간편비밀번호 해시(bcrypt)와 기기 토큰. 평문은 로그와 DB 어디에도 남기지 않는다."""
import hashlib
import secrets

import bcrypt


def hash_secret(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def check_secret(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def new_device_token() -> str:
    """무작위 토큰(32바이트 이상). 쿠키에는 원문을, DB 에는 해시만 둔다."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
