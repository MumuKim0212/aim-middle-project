"""개발용 DB 초기화: public 스키마를 통째로 지우고 테이블을 다시 만든 뒤 시드를 넣는다.

테이블 구조가 바뀌었을 때(예: members → users) 쓴다. 로컬 개발 DB 의 데이터가 모두 사라진다.
실행: backend 폴더에서  python reset_db.py --yes
"""
import sys

from sqlalchemy import text

from app import models as m
from app.db import SessionLocal, engine
from app.seed import seed

if "--yes" not in sys.argv:
    sys.exit("로컬 개발 DB 의 모든 데이터가 지워집니다. 계속하려면 --yes 를 붙여 실행하세요.")

with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
m.Base.metadata.create_all(engine)
with SessionLocal() as db:
    seed(db)
print("DB 를 초기화하고 시드를 넣었습니다.")
