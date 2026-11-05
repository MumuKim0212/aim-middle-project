import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# PostgreSQL 기준. docker-compose.yml 의 DB 와 같은 기본값이며 환경변수로 덮어쓴다.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
