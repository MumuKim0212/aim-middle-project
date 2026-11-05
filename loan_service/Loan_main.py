"""[역할] 대출 서비스 실행 진입점: DB(스키마+기준 데이터)를 준비하고 콘솔 메뉴로 대출 서비스를 체험하게 한다."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loan import config  # noqa: E402
from loan.database import Database  # noqa: E402
from loan.seed import seed  # noqa: E402


def open_db(path: str | Path = config.DB_PATH, reset: bool = False) -> Database:
    """DB 파일을 열고 스키마·기준 데이터를 준비한다. reset이면 기존 파일을 지우고 새로 만든다."""
    p = Path(path)
    if reset and str(path) != ":memory:":
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(p) + suffix)
            if f.exists():
                f.unlink()
    db = Database(path)
    db.init_schema()
    seed(db)
    return db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OO은행 대출 서비스 체험(콘솔)")
    ap.add_argument("--reset", action="store_true", help="DB를 지우고 새로 만든다")
    ap.add_argument("--auto", action="store_true", help="체험 고객 21개 조합을 자동 실행하고 결과표만 출력한다")
    ap.add_argument("--db", default=str(config.DB_PATH), help="DB 파일 경로(기본 data/loan_service.db)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    db = open_db(args.db, args.reset)
    try:
        from loan.cli import demo_all, main_menu
        if args.auto:
            demo_all(db)
            ok, n = db.verify_audit_chain()
            print(f"  감사 로그 {n}건 · {'정상' if ok else '불일치'}")
        else:
            main_menu(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
