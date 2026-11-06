"""대출 월 상환 자동이체 배치. 적금 자동이체(accounts/batch.py)와 같은 방식의 백그라운드 작업이다.
매일 00:20(KST)에 돌아 00:10 적금 자동이체 뒤에 처리하고, 서버가 꺼져 있던 동안 지나간 납입일은 다음 실행에서 처리한다."""
import asyncio
import logging
from datetime import datetime, timedelta

from ..accounts.service import KST
from ..db import SessionLocal
from .management import auto_debit

log = logging.getLogger("loan.batch")


def _run() -> None:
    with SessionLocal() as db:
        log.info("대출 자동이체 %d회차 처리", auto_debit(db))


async def auto_debit_loop() -> None:
    while True:
        now = datetime.now(KST)
        nxt = now.replace(hour=0, minute=20, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            await asyncio.to_thread(_run)
        except Exception:  # 한 번 실패해도 내일 다시 돈다
            log.exception("대출 자동이체 배치 실패")
