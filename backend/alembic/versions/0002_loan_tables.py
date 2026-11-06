"""loan tables (60 tables, append-only audit log trigger)

대출 테이블은 ORM 모델이 아니라 SQL 로 정의한다(app/loan/schema.sql 이 현재 전체 DDL 이고 ERD 생성기가 읽는다).
이 마이그레이션은 그 DDL 의 2026-11-06 시점 복사본(alembic/sql/0002_loan_schema.sql)을 실행한다. 복사본은 고치지 않는다:
대출 스키마를 바꿀 때는 새 마이그레이션을 쓰고 app/loan/schema.sql 도 같이 고친다(tests/test_migrations.py 가 둘이 어긋나면 알려 준다).

Revision ID: 0002
Revises: 0001
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL = Path(__file__).resolve().parent.parent / "sql" / "0002_loan_schema.sql"


def upgrade() -> None:
    # 여러 문장·$$ 함수 본문·% 가 들어 있어 자리표시자 해석 없이 드라이버로 그대로 보낸다
    op.get_bind().connection.driver_connection.cursor().execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("대출 테이블 되돌리기는 지원하지 않는다. 개발 DB 는 python reset_db.py --yes 로 다시 만든다.")
