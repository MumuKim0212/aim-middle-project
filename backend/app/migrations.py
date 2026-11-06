"""Alembic 을 코드에서 부르는 도우미: 마이그레이션 실행(reset_db, 시험)과 서버 시작 전 확인."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection, Engine

BACKEND = Path(__file__).resolve().parent.parent


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["skip_logging"] = True  # 서버·시험의 로그 설정을 덮어쓰지 않는다
    if connection is not None:
        cfg.attributes["connection"] = connection  # 이 연결(시험의 전용 스키마)에 마이그레이션을 돌린다
    return cfg


def upgrade_head(connection: Connection | None = None) -> None:
    command.upgrade(alembic_config(connection), "head")


def ensure_migrated(engine: Engine) -> None:
    """DB 가 최신 마이그레이션이 아니면 서버를 켜지 않고 해야 할 일을 알려 준다(테이블이 없다는 알 수 없는 오류 대신)."""
    with engine.connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    head = set(ScriptDirectory.from_config(alembic_config()).get_heads())
    if current != head:
        raise RuntimeError(
            "DB 마이그레이션이 최신이 아닙니다 (DB: %s, 최신: %s). cd backend && alembic upgrade head 를 실행하세요. "
            "예전 create_all 로 만든 현재 구조의 DB 라면 alembic stamp head 를 실행하세요."
            % (", ".join(sorted(current)) or "없음", ", ".join(sorted(head))))
