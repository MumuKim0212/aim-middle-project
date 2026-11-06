"""[역할] 대출 모듈의 DB 래퍼: 서버의 SQLAlchemy 세션(PostgreSQL)과 같은 트랜잭션을 쓰고, 감사 로그(해시 체인)를 남긴다. 모든 SQL은 파라미터 바인딩만 쓴다."""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg.types.string import TextLoader
from sqlalchemy.orm import Session

from . import config
from .security import sha256

GENESIS = "0" * 64
AUDIT_LOCK = 7101  # 해시 체인이 갈라지지 않게 감사 기록을 한 줄로 세우는 advisory lock 번호
# 허용 목록: schema.sql 에 정의된 대출 테이블만 insert/update 대상이다.
LOAN_TABLES = frozenset(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", config.SCHEMA_PATH.read_text(encoding="utf-8")))
_bool_cols: dict[str, frozenset[str]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(obj: Any) -> str:
    """JSONB 컬럼 저장용(한글 그대로, 키 정렬로 해시 재현 가능)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class Database:
    """얇은 DB 래퍼. 문자열 조합 SQL을 막기 위해 execute는 반드시 params를 받는다.
    서버 세션과 같은 연결을 쓰므로 계좌 입출금(accounts.service)과 한 트랜잭션으로 묶인다. 커밋은 호출한 쪽이 한다."""

    def __init__(self, session: Session):
        self.session = session
        self._depth = 0

    def _cursor(self):
        """shortcut: 날짜·시각·JSON 을 문자열로 읽는다(기존 로직이 ISO 문자열·json.loads 를 전제), 로직을 네이티브 타입으로 바꿀 때 걷어낸다."""
        cur = self.session.connection().connection.driver_connection.cursor(row_factory=dict_row)
        for t in ("date", "timestamp", "timestamptz", "json", "jsonb"):
            cur.adapters.register_loader(t, TextLoader)
        return cur

    # ---- 스키마 ----
    def table_names(self) -> list[str]:
        rows = self._cursor().execute(
            "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = current_schema()").fetchall()
        return sorted(r["t"] for r in rows if r["t"] in LOAN_TABLES)

    # ---- 실행 (파라미터 바인딩 강제) ----
    @staticmethod
    def _guard(sql: str, params: tuple | dict) -> None:
        if not isinstance(params, (tuple, dict)):
            raise TypeError("params must be tuple or dict (SQL injection guard)")
        if ";" in sql.strip().rstrip(";"):
            raise ValueError("multiple statements are not allowed")

    def execute(self, sql: str, params: tuple | dict = ()):
        self._guard(sql, params)
        # 호출부는 ? 자리표시자를 쓴다 → psycopg 의 %s 로 바꾸고, 문장 속 % 는 이스케이프한다.
        return self._cursor().execute(sql.replace("%", "%%").replace("?", "%s"), params)

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        return self.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        return self.execute(sql, params).fetchall()

    def _check_table(self, table: str) -> None:
        """식별자 형식 + schema.sql 에 있는 대출 테이블만 허용(허용 목록)."""
        if not table.isidentifier() or table not in LOAN_TABLES:
            raise ValueError(f"unknown table {table}")

    def _bools(self, table: str) -> frozenset[str]:
        if table not in _bool_cols:
            rows = self._cursor().execute(
                "SELECT column_name AS c FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = %s AND data_type = 'boolean'", (table,)).fetchall()
            _bool_cols[table] = frozenset(r["c"] for r in rows)
        return _bool_cols[table]

    def _val(self, table: str, col: str, v: Any) -> Any:
        if isinstance(v, (dict, list)):
            return dumps(v)
        if col in self._bools(table) and isinstance(v, int) and not isinstance(v, bool):
            return bool(v)  # 호출부가 0/1 로 넘겨도 BOOLEAN 컬럼에는 bool 로 저장
        return v

    def insert(self, table: str, row: dict) -> None:
        """테이블·컬럼 이름은 코드 상수만 허용(식별자 검증), 값은 바인딩."""
        self._check_table(table)
        if not row or not all(k.isidentifier() for k in row):
            raise ValueError("invalid identifier")
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        vals = tuple(self._val(table, k, v) for k, v in row.items())
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", vals)

    def update(self, table: str, key: dict, values: dict) -> int:
        self._check_table(table)
        if not key or not values:                       # WHERE 없는 전체 갱신 금지
            raise ValueError("update requires key and values")
        if not all(k.isidentifier() for k in {**key, **values}):
            raise ValueError("invalid identifier")
        sets = ", ".join(f"{k} = ?" for k in values)
        where = " AND ".join(f"{k} = ?" for k in key)
        vals = tuple(self._val(table, k, v) for k, v in values.items()) + tuple(key.values())
        return self.execute(f"UPDATE {table} SET {sets} WHERE {where}", vals).rowcount

    # ---- 트랜잭션 ----
    @contextmanager
    def tx(self) -> Iterator["Database"]:
        """중첩 가능한 트랜잭션. 예외가 나면 이 구간만 되돌린다(SAVEPOINT 사용)."""
        name = f"sp{self._depth}"
        cur = self._cursor()
        cur.execute(f"SAVEPOINT {name}")
        self._depth += 1
        try:
            yield self
        except Exception:
            self._depth -= 1
            cur.execute(f"ROLLBACK TO {name}")
            cur.execute(f"RELEASE {name}")
            raise
        else:
            self._depth -= 1
            cur.execute(f"RELEASE {name}")

    # ---- 감사 로그 (해시 체인) ----
    def audit(self, entity: str, entity_id: str, action: str, payload: dict, actor: str = "system") -> None:
        """내용은 해시로만 남기고, 직전 행 해시와 이어 붙여 위변조를 탐지할 수 있게 한다."""
        self.execute("SELECT pg_advisory_xact_lock(?)", (AUDIT_LOCK,))
        prev = self.one("SELECT row_hash FROM loan_audit_log ORDER BY audit_seq DESC LIMIT 1")
        prev_hash = prev["row_hash"] if prev else GENESIS
        payload_hash = sha256(dumps(payload))
        created = now_iso()
        row_hash = sha256("|".join([prev_hash, entity, entity_id, action, actor, payload_hash, created]))
        self.insert("loan_audit_log", {"entity": entity, "entity_id": entity_id, "action": action, "actor": actor,
                                       "payload_hash": payload_hash, "prev_hash": prev_hash, "row_hash": row_hash,
                                       "created_at": created})

    def verify_audit_chain(self) -> tuple[bool, int]:
        """감사 로그 전체를 다시 계산해 끊어진 곳이 없는지 확인. (정상 여부, 검사 행 수)."""
        prev = GENESIS
        rows = self.all("SELECT * FROM loan_audit_log ORDER BY audit_seq")
        for r in rows:
            created = datetime.fromisoformat(r["created_at"]).astimezone(timezone.utc).isoformat(timespec="seconds")
            expect = sha256("|".join([prev, r["entity"], r["entity_id"], r["action"], r["actor"], r["payload_hash"], created]))
            if r["prev_hash"] != prev or r["row_hash"] != expect:
                return False, len(rows)
            prev = r["row_hash"]
        return True, len(rows)
