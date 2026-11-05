from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from . import models as m
from .db import get_db
from .seed import DEMO_MEMBER_ID


def current_member(db: Session = Depends(get_db)) -> m.Member:
    """TODO: 로그인(토큰) 담당 확정 후 교체. 지금은 데모 회원 고정."""
    member = db.get(m.Member, DEMO_MEMBER_ID)
    if not member:
        raise HTTPException(401, "UNAUTHORIZED")
    return member
