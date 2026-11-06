"""Alembic 실행 환경. 접속 주소는 app/db.py 의 DATABASE_URL 을 쓴다(.env, 환경변수).

시험은 config.attributes["connection"] 으로 연결을 직접 넘긴다(전용 스키마에 마이그레이션을 돌려 보기 위해).
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models
from app.db import DATABASE_URL

config = context.config
if config.config_file_name and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """모델에 없는 DB 테이블(대출 테이블 등 SQL 마이그레이션으로 관리하는 것)은 autogenerate 가 지우려 하지 않게 건너뛴다."""
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True


def _configure(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, include_object=include_object)


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as conn:
        _configure(conn)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
