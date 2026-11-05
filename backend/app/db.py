import os

from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# backend/.env 가 있으면 먼저 읽는다(키 등 비밀값은 .env 에만 둔다). 이미 설정된 환경변수가 우선한다.
load_dotenv()

# PostgreSQL 기준. docker-compose.yml 의 DB 와 같은 기본값이며 환경변수로 덮어쓴다.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://aimbank:aimbank@localhost:5433/aimbank",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
