"""개발용 DB 초기화: public 스키마를 통째로 지우고 Alembic 마이그레이션(alembic upgrade head)으로 테이블을 다시 만든 뒤 시드를 넣는다.

마이그레이션 없이 모델만 고쳐 구조가 어긋났거나 시드를 바꿨을 때 쓴다. 로컬 개발 DB 의 데이터가 모두 사라진다.
스키마 변경을 반영하는 일상적인 방법은 이 스크립트가 아니라 alembic upgrade head 다(데이터가 남는다).
실행: backend 폴더에서  python reset_db.py --yes
"""
import sys

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.migrations import upgrade_head
from app.seed import seed

if "--yes" not in sys.argv:
    sys.exit("로컬 개발 DB 의 모든 데이터가 지워집니다. 계속하려면 --yes 를 붙여 실행하세요.")

with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
upgrade_head()
with SessionLocal() as db:
    seed(db)
print("DB 를 초기화하고 시드를 넣었습니다.")
