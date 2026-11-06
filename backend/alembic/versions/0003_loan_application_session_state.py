"""loan_application.session_state: 신청 진행 상태를 DB 에도 남겨 서버를 다시 켠 뒤 복원한다

대출 스키마를 바꿀 때는 app/loan/schema.sql 도 같이 고친다(tests/test_migrations.py 가 어긋나면 알려 준다).

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE loan_application ADD COLUMN session_state JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE loan_application DROP COLUMN session_state")
