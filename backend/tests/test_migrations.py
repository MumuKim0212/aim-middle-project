"""마이그레이션 점검: Alembic 으로 만든 DB 가 모델(ORM)과 app/loan/schema.sql 이 정의한 구조와 같은지, 서버 시작 전 확인이 동작하는지.

모델이나 schema.sql 을 고치고 마이그레이션을 빠뜨리면 여기서 어긋난 열·인덱스를 알려 준다.
전용 스키마 mig_a·mig_b 를 만들었다 지우므로 개발 DB(aimbank, 5432)에서 그대로 돌려도 된다:
  python -m pytest backend/tests/test_migrations.py
"""
import os
import re
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models as m  # noqa: E402
from app.loan import config as loan_config  # noqa: E402
from app.migrations import alembic_config, ensure_migrated, upgrade_head  # noqa: E402

URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank")


def engine_in(schema: str):
    return create_engine(URL, connect_args={"options": f"-c search_path={schema}"})


@pytest.fixture
def schemas():
    names = ("mig_a", "mig_b")
    root = create_engine(URL)
    with root.begin() as c:
        for n in names:
            c.execute(text(f"DROP SCHEMA IF EXISTS {n} CASCADE"))
            c.execute(text(f"CREATE SCHEMA {n}"))
    yield names
    with root.begin() as c:
        for n in names:
            c.execute(text(f"DROP SCHEMA IF EXISTS {n} CASCADE"))
    root.dispose()


def shape(engine, schema: str) -> dict:
    """열(이름·타입·null 허용·identity)과 인덱스·제약 이름으로 구조를 요약한다. alembic_version 은 뺀다."""
    with engine.connect() as c:
        cols = {(r[0], r[1]): tuple(r[2:]) for r in c.execute(text(
            "SELECT table_name, column_name, data_type, is_nullable, is_identity, identity_generation FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name <> 'alembic_version'"), {"s": schema})}
        idx = {r[0]: re.sub(rf"\b{schema}\.", "", r[1]) for r in c.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :s AND tablename <> 'alembic_version'"), {"s": schema})}
        cons = {r[0] for r in c.execute(text(
            "SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = :s AND table_name <> 'alembic_version' "
            "AND constraint_type IN ('CHECK','FOREIGN KEY','UNIQUE') AND constraint_name NOT LIKE '%_not_null'"), {"s": schema})}
    return {"columns": cols, "indexes": idx, "constraints": cons}


def test_single_head():
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_migrations_match_models_and_loan_schema(schemas):
    a, b = schemas
    ea, eb = engine_in(a), engine_in(b)
    with ea.begin() as c:
        upgrade_head(c)
    m.Base.metadata.create_all(eb)  # 기준: 모델 + 대출 schema.sql
    with eb.begin() as c:
        c.connection.driver_connection.cursor().execute(loan_config.SCHEMA_PATH.read_text(encoding="utf-8"))
    sa, sb = shape(ea, a), shape(eb, b)
    for part in ("columns", "indexes", "constraints"):
        only_migration = set(sa[part]) - set(sb[part])
        only_models = set(sb[part]) - set(sa[part])
        assert not only_migration and not only_models, f"{part}: 마이그레이션에만 {sorted(only_migration)[:5]}, 모델·schema.sql 에만 {sorted(only_models)[:5]}"
        assert sa[part] == sb[part], f"{part} 내용이 다름: " + str([k for k in sa[part] if sa[part][k] != sb[part][k]][:5])
    ea.dispose()
    eb.dispose()


def test_ensure_migrated_blocks_unmigrated_db(schemas):
    a, _ = schemas
    e = engine_in(a)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        ensure_migrated(e)
    with e.begin() as c:
        upgrade_head(c)
    ensure_migrated(e)  # 최신이면 통과
    e.dispose()
