"""[역할] 콘솔 체험 진입점: cd backend && python -m app.loan [--auto]. 회원 없이(user_id 없음) 대출 흐름을 눌러 보거나 체험 고객 21개 조합을 자동 실행한다."""
from __future__ import annotations

import argparse
import sys

from ..db import SessionLocal
from .cli import demo_all, main_menu
from .database import Database
from .seed import seed


def main() -> int:
    ap = argparse.ArgumentParser(description="OO은행 대출 서비스 체험(콘솔)")
    ap.add_argument("--auto", action="store_true", help="체험 고객 21개 조합을 자동 실행하고 결과표만 출력한다")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with SessionLocal() as session:
        db = Database(session)
        db.init_schema()
        seed(db)
        session.commit()
        try:
            if args.auto:
                demo_all(db)
                ok, n = db.verify_audit_chain()
                print(f"  감사 로그 {n}건 · {'정상' if ok else '불일치'}")
            else:
                main_menu(db)
        finally:
            session.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
