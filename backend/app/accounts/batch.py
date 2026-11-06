"""적금 자동이체 배치(계좌.md 5.3). 별도 서버·의존성 없이 앱 시작 때 만드는 백그라운드 작업이다.
매일 00:10(KST)에 돌고, 서버가 꺼져 있던 동안 지나간 납입일은 다음 실행에서 처리한다."""
import asyncio
import logging
from datetime import datetime, timedelta

from ..db import SessionLocal
from .service import KST, run_auto_pay

log = logging.getLogger("accounts.batch")


def _run() -> None:
    with SessionLocal() as db:
        log.info("자동이체 %d건 처리", run_auto_pay(db))


async def auto_pay_loop() -> None:
    while True:
        now = datetime.now(KST)
        nxt = now.replace(hour=0, minute=10, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            await asyncio.to_thread(_run)
        except Exception:  # 한 번 실패해도 내일 다시 돈다
            log.exception("자동이체 배치 실패")
