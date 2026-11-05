"""[역할] SQLite 연결·트랜잭션·감사 로그(해시 체인)를 관리한다. 모든 SQL은 파라미터 바인딩만 쓴다."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config
from .security import sha256

GENESIS = "0" * 64


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(obj: Any) -> str:
    """JSONB 컬럼 저장용(한글 그대로, 키 정렬로 해시 재현 가능)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class Database:
    """얇은 DB 래퍼. 문자열 조합 SQL을 막기 위해 execute는 반드시 params를 받는다."""

    def __init__(self, path: Path | str = config.DB_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, detect_types=0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._depth = 0

    # ---- 스키마 ----
    def init_schema(self) -> None:
        self.conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))

    def table_names(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    # ---- 실행 (파라미터 바인딩 강제) ----
    @staticmethod
    def _guard(sql: str, params: tuple | dict) -> None:
        if not isinstance(params, (tuple, dict)):
            raise TypeError("params must be tuple or dict (SQL injection guard)")
        if ";" in sql.strip().rstrip(";"):
            raise ValueError("multiple statements are not allowed")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        self._guard(sql, params)
        return self.conn.execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def _check_table(self, table: str) -> None:
        """식별자 형식 + 실제 스키마에 있는 테이블만 허용(허용 목록)."""
        if not table.isidentifier():
            raise ValueError("invalid identifier")
        if not hasattr(self, "_tables") or table not in self._tables:
            self._tables = set(self.table_names())
            if table not in self._tables:
                raise ValueError(f"unknown table {table}")

    def insert(self, table: str, row: dict) -> None:
        """테이블·컬럼 이름은 코드 상수만 허용(식별자 검증), 값은 바인딩."""
        self._check_table(table)
        if not row or not all(k.isidentifier() for k in row):
            raise ValueError("invalid identifier")
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        vals = tuple(dumps(v) if isinstance(v, (dict, list)) else v for v in row.values())
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", vals)

    def update(self, table: str, key: dict, values: dict) -> int:
        self._check_table(table)
        if not key or not values:                       # WHERE 없는 전체 갱신 금지
            raise ValueError("update requires key and values")
        if not all(k.isidentifier() for k in {**key, **values}):
            raise ValueError("invalid identifier")
        sets = ", ".join(f"{k} = ?" for k in values)
        where = " AND ".join(f"{k} = ?" for k in key)
        vals = tuple(dumps(v) if isinstance(v, (dict, list)) else v for v in values.values()) + tuple(key.values())
        return self.execute(f"UPDATE {table} SET {sets} WHERE {where}", vals).rowcount

    # ---- 트랜잭션 ----
    @contextmanager
    def tx(self) -> Iterator["Database"]:
        """중첩 가능한 트랜잭션. 예외가 나면 전부 되돌린다(SAVEPOINT 사용)."""
        name = f"sp{self._depth}"
        self.conn.execute(f"SAVEPOINT {name}")
        self._depth += 1
        try:
            yield self
        except Exception:
            self._depth -= 1
            self.conn.execute(f"ROLLBACK TO {name}")
            self.conn.execute(f"RELEASE {name}")
            raise
        else:
            self._depth -= 1
            self.conn.execute(f"RELEASE {name}")

    # ---- 감사 로그 (해시 체인) ----
    def audit(self, entity: str, entity_id: str, action: str, payload: dict, actor: str = "system") -> None:
        """내용은 해시로만 남기고, 직전 행 해시와 이어 붙여 위변조를 탐지할 수 있게 한다."""
        prev = self.one("SELECT row_hash FROM audit_log ORDER BY audit_seq DESC LIMIT 1")
        prev_hash = prev["row_hash"] if prev else GENESIS
        payload_hash = sha256(dumps(payload))
        created = now_iso()
        row_hash = sha256("|".join([prev_hash, entity, entity_id, action, actor, payload_hash, created]))
        self.insert("audit_log", {"entity": entity, "entity_id": entity_id, "action": action, "actor": actor,
                                  "payload_hash": payload_hash, "prev_hash": prev_hash, "row_hash": row_hash,
                                  "created_at": created})

    def verify_audit_chain(self) -> tuple[bool, int]:
        """감사 로그 전체를 다시 계산해 끊어진 곳이 없는지 확인. (정상 여부, 검사 행 수)."""
        prev = GENESIS
        rows = self.all("SELECT * FROM audit_log ORDER BY audit_seq")
        for r in rows:
            expect = sha256("|".join([prev, r["entity"], r["entity_id"], r["action"], r["actor"], r["payload_hash"], r["created_at"]]))
            if r["prev_hash"] != prev or r["row_hash"] != expect:
                return False, len(rows)
            prev = r["row_hash"]
        return True, len(rows)

    def close(self) -> None:
        self.conn.close()
