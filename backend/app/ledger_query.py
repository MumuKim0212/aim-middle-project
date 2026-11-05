"""가계부 자유 질문: 정해 둔 의도에 안 맞는 조회 질문을 읽기 전용 SQL 로 푼다(text-to-SQL, 안전장치 포함).

핵심은 "프롬프트를 믿지 않는 것"이다. LLM 이 어떤 SQL 을 만들어도 아래가 DB·코드 차원에서 막는다.
  1. 가상 표(CTE)만 본다 : 내 user_id 로 이미 걸러진 표(spending, income …)만 이름으로 노출하고,
                           user_id 는 바인드 값으로 박아서 SQL 안에서 바꿀 수 없다.
  2. 읽기 전용 역할      : SET LOCAL ROLE ledger_ro. 필요한 열에만 SELECT 권한이 있는 역할(비밀번호·계좌번호 열은 없음).
  3. 읽기 전용 트랜잭션  : SET TRANSACTION READ ONLY. 쓰기는 DB 가 거부한다.
  4. 쿼리 검사(sqlglot)  : SELECT 한 문장, 허용한 표·함수만, 서브쿼리 포함 전부 검사. 그 밖은 실행하지 않는다.
  5. 시간·행 제한        : statement_timeout 3초, 최대 50행.
조회 결과의 숫자만 답변에 쓸 수 있고(ledger_answer 의 숫자 검증), 못 풀면 "계산하지 못했다"고 솔직히 말한다.
데이터를 바꾸는 일(기록·예산 수정)은 이 경로가 아니라 정해 둔 함수로만 한다.
"""
import json
import logging
from datetime import date, datetime
from decimal import Decimal

import sqlglot
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlglot import exp

from .gemini import LlmUnavailable, generate_json

log = logging.getLogger("ledger.query")

ROLE = "ledger_ro"
MAX_ROWS = 50
TIMEOUT_MS = 3000

# ───────────── 가상 표 ─────────────
# 이름 → (설명, CTE 정의). :mid 는 로그인한 회원 id 바인드 값.
VIRTUAL: dict[str, tuple[str, str]] = {
    "spending": (
        "카드 지출 내역. amount 는 원 단위 순지출(승인은 +, 취소는 -)이라 SUM 하면 순지출. "
        "date(날짜), merchant(사용처), category(배달·외식·장보기·쇼핑·교통·생활·기타), kind(approval|cancel)",
        "SELECT t.id, t.occurred_at::date AS date, t.merchant, COALESCE(lc.category, '기타') AS category, "
        "CASE WHEN t.kind = 'approval' THEN t.amount ELSE -t.amount END AS amount, t.kind "
        "FROM card_transactions t JOIN cards c ON c.id = t.card_id "
        "LEFT JOIN ledger_tx_category lc ON lc.card_transaction_id = COALESCE(t.original_id, t.id) "
        "WHERE c.user_id = :mid",
    ),
    "income": (
        "내 계좌로 들어온 돈(수입). date, source(월급·용돈 등 이름), amount",
        "SELECT a.occurred_at::date AS date, COALESCE(a.counterparty, a.memo, '입금') AS source, a.amount "
        "FROM account_transactions a JOIN accounts ac ON ac.id = a.account_id "
        "WHERE ac.user_id = :mid AND a.kind IN ('deposit', 'transfer_in')",
    ),
    "monthly_budgets": (
        "월별 총 예산. month('YYYY-MM'), total_amount",
        "SELECT b.month, b.total_amount FROM budgets b WHERE b.user_id = :mid",
    ),
    "category_limits": (
        "월별 분류 예산. month, category, amount",
        "SELECT b.month, cb.category, cb.amount FROM category_budgets cb JOIN budgets b ON b.id = cb.budget_id "
        "WHERE b.user_id = :mid",
    ),
    "payment_checks": (
        "결제 전 확인 기록. date, amount, category, result(allowed|held), over_amount",
        "SELECT p.created_at::date AS date, p.amount, p.category, p.result, p.over_amount "
        "FROM payment_attempts p WHERE p.user_id = :mid",
    ),
    "upcoming_payments": (
        "예정 출금(카드대금·고정비). due_date, amount, type(card_bill|fixed|loan_repayment), status",
        "SELECT o.due_date, o.amount, o.type, o.status FROM planned_outflows o WHERE o.user_id = :mid",
    ),
    "saving_goals": (
        "월 저축 목표. month, name, target_amount",
        "SELECT g.month, g.name, g.target_amount FROM ledger_goals g WHERE g.user_id = :mid",
    ),
}

# 읽기 전용 역할에 줄 열 단위 SELECT 권한(원본 표). 비밀번호·계좌번호 같은 열은 넣지 않는다.
GRANTS: dict[str, list[str]] = {
    "card_transactions": ["id", "card_id", "kind", "occurred_at", "merchant", "amount", "original_id"],
    "cards": ["id", "user_id"],
    "ledger_tx_category": ["card_transaction_id", "category"],
    "budgets": ["id", "user_id", "month", "total_amount"],
    "category_budgets": ["budget_id", "category", "amount"],
    "account_transactions": ["account_id", "kind", "amount", "occurred_at", "counterparty", "memo"],
    "accounts": ["id", "user_id"],
    "payment_attempts": ["user_id", "amount", "category", "result", "over_amount", "created_at"],
    "planned_outflows": ["user_id", "due_date", "amount", "type", "status"],
    "ledger_goals": ["user_id", "month", "name", "target_amount"],
}

READY = False


def setup(engine: Engine) -> bool:
    """읽기 전용 역할과 열 권한을 만든다(여러 번 불러도 같다). 권한이 없으면 자유 질문만 꺼 둔다."""
    global READY
    try:
        with engine.begin() as conn:
            conn.execute(text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') "
                f"THEN CREATE ROLE {ROLE} NOLOGIN; END IF; END $$"))
            conn.execute(text(f"GRANT {ROLE} TO CURRENT_USER"))
            for table, cols in GRANTS.items():
                conn.execute(text(f"REVOKE ALL ON {table} FROM {ROLE}"))
                conn.execute(text(f"GRANT SELECT ({', '.join(cols)}) ON {table} TO {ROLE}"))
        READY = True
    except Exception as e:  # 권한 부족 등
        READY = False
        log.warning("읽기 전용 역할 준비 실패, 자유 질문은 쓰지 않는다: %s", type(e).__name__)
    return READY


# ───────────── 쿼리 검사 ─────────────

# sqlglot 버전마다 클래스 이름이 조금 달라서, 있는 것만 허용 목록에 넣는다
_ALLOWED_FUNC_NAMES = (
    "Sum", "Count", "Avg", "Min", "Max", "Coalesce", "Round", "Abs", "Greatest", "Least", "Lower", "Upper", "Length",
    "DateTrunc", "Extract", "TimeToStr", "Nullif", "Cast", "CurrentDate", "If", "RowNumber", "Rank", "DenseRank",
    "Floor", "Ceil", "Concat", "Substring", "Trim", "Median", "Stddev", "Quantile", "Case", "DateAdd", "DateSub", "DateDiff",
)
_ALLOWED_FUNCS = tuple(getattr(exp, n) for n in _ALLOWED_FUNC_NAMES if hasattr(exp, n))
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Set, exp.Into,
    exp.Lock, exp.Use, exp.Transaction, exp.Commit, exp.Rollback, exp.Merge,
)


class QueryRejected(Exception):
    pass


def validate_sql(sql: str, user_id: int) -> str:
    """통과하면 가상 표 정의를 앞에 붙이고 행 수를 제한한 최종 SQL 을, 아니면 QueryRejected 를 던진다."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise QueryRejected("empty")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.SqlglotError as e:
        raise QueryRejected("parse") from e
    if len(statements) != 1 or statements[0] is None:
        raise QueryRejected("not a single statement")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise QueryRejected("not a select")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise QueryRejected("forbidden statement")
        if isinstance(node, exp.Func) and not isinstance(node, _ALLOWED_FUNCS):
            raise QueryRejected(f"function not allowed: {node.key}")
        if isinstance(node, exp.Anonymous):
            raise QueryRejected(f"function not allowed: {node.name}")
        if isinstance(node, (exp.Parameter, exp.Placeholder)):
            raise QueryRejected("parameter not allowed")
    # 사용자가 쓴 WITH 의 이름은 허용하되, 가상 표 이름과 겹치면 안 된다
    user_ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    if user_ctes & set(VIRTUAL):
        raise QueryRejected("cte name clash")
    allowed = set(VIRTUAL) | user_ctes
    for table in tree.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog") or table.name.lower() not in allowed:
            raise QueryRejected(f"table not allowed: {table.name}")
    body = tree.sql(dialect="postgres")
    defs = ", ".join(f"{name} AS ({cte})" for name, (_, cte) in VIRTUAL.items())
    # 사용자 WITH 는 앞의 가상 표 정의와 하나의 WITH 로 합친다
    if tree.args.get("with"):
        inner = tree.copy()
        w = inner.args.pop("with")
        user_defs = ", ".join(c.sql(dialect="postgres") for c in w.expressions)
        body = inner.sql(dialect="postgres")
        defs = f"{defs}, {user_defs}"
    return f"WITH {defs} SELECT * FROM ({body}) AS _q LIMIT {MAX_ROWS + 1}"


def _jsonable(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else round(float(v), 1)
    if isinstance(v, float):
        return int(v) if v == int(v) else round(v, 1)
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    return v


def execute(engine: Engine, user_id: int, final_sql: str) -> tuple[list[str], list[list]]:
    """읽기 전용 역할·읽기 전용 트랜잭션·시간 제한 안에서 실행한다."""
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL ROLE {ROLE}"))
            conn.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
            res = conn.execute(text(final_sql), {"mid": user_id})
            cols = list(res.keys())
            rows = [[_jsonable(v) for v in r] for r in res.fetchmany(MAX_ROWS + 1)]
    return cols, rows[:MAX_ROWS]


# ───────────── SQL 생성(LLM) ─────────────

_SYSTEM = """너는 가계부 앱의 '조회 SQL 작성기'다. 사용자의 한국어 질문을 PostgreSQL SELECT 한 문장으로 바꾼다.
오늘은 {today} 이고 이번 달은 '{month}' 이다.

쓸 수 있는 표(이 표만 있다. 다른 표·스키마는 없다):
{tables}

규칙:
- SELECT 한 문장만. INSERT/UPDATE/DELETE, 세미콜론으로 이어 쓰기, 주석, 함수 만들기 금지.
- 위 표 이름만 쓴다. 허용 함수: SUM COUNT AVG MIN MAX ROUND COALESCE ABS GREATEST LEAST DATE_TRUNC EXTRACT TO_CHAR CAST 정도다.
- spending.amount 는 이미 승인(+)/취소(-)를 반영한 순지출이다. 지출 합계는 SUM(amount).
- 금액은 원 단위 정수다. 요일은 EXTRACT(DOW FROM date) (0=일요일, 6=토요일).
- '이번 달'은 TO_CHAR(date,'YYYY-MM') = '{month}' 처럼 비교한다. 기간이 없으면 전체를 본다.
- 결과 열 이름은 한국어 별칭으로 붙인다(예: AS 합계).
- 결과는 많아도 50행 이하가 되게 GROUP BY·ORDER BY·LIMIT 을 쓴다.
- 가계부 데이터로 풀 수 없는 질문이면 answerable 을 false 로 하고 sql 은 빈 문자열로 둔다.
basis: 어떤 기간·기준으로 계산했는지 한국어 한 문장(예: '이번 달 카드 지출을 요일별로 합쳤어요')."""

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answerable": {"type": "BOOLEAN"},
        "sql": {"type": "STRING"},
        "basis": {"type": "STRING"},
    },
    "required": ["answerable", "sql", "basis"],
}


def _system(today: date) -> str:
    tables = "\n".join(f"- {name}: {desc}" for name, (desc, _) in VIRTUAL.items())
    return _SYSTEM.format(today=today.isoformat(), month=today.strftime("%Y-%m"), tables=tables)


def run(engine: Engine, user_id: int, question: str, today: date | None = None) -> dict:
    """질문 → SQL 생성 → 검사 → 실행. 결과는 항상 {ok, basis, columns, rows, sql, error} 모양이다."""
    today = today or date.today()
    out = {"ok": False, "basis": "", "columns": [], "rows": [], "sql": "", "error": None}
    if not READY:
        out["error"] = "unavailable"
        return out
    try:
        raw = generate_json(_system(today), question, _SCHEMA, timeout_default=8.0)
    except LlmUnavailable as e:
        out["error"] = f"llm:{e}"
        return out
    out["basis"] = str(raw.get("basis") or "")[:120]
    if not raw.get("answerable") or not str(raw.get("sql") or "").strip():
        out["error"] = "unanswerable"
        return out
    out["sql"] = str(raw["sql"]).strip()[:2000]
    try:
        final_sql = validate_sql(out["sql"], user_id)
    except QueryRejected as e:
        log.warning("자유 질문 SQL 거부: %s", e)
        out["error"] = f"rejected:{e}"
        return out
    try:
        cols, rows = execute(engine, user_id, final_sql)
    except Exception as e:  # 열 이름 오류, 시간 초과 등
        log.warning("자유 질문 SQL 실행 실패: %s", type(e).__name__)
        out["error"] = f"exec:{type(e).__name__}"
        return out
    out.update(ok=True, columns=cols, rows=rows)
    return out


def facts_from(result: dict, question: str) -> dict:
    """답변 문장에 쓸 사실. 조회 결과의 값만 들어간다(숫자 검증이 이 값들을 기준으로 한다)."""
    if not result["ok"]:
        return {"verdict": "info", "질문": "자유 조회", "계산 불가": True}
    if not result["rows"]:
        return {"verdict": "info", "질문": "자유 조회", "계산 기준": result["basis"], "결과 없음": True}
    rows = [dict(zip(result["columns"], r)) for r in result["rows"][:15]]
    return {"verdict": "info", "질문": "자유 조회", "계산 기준": result["basis"], "조회 결과": rows,
            "조회 행 수": len(result["rows"])}


def public(result: dict) -> dict:
    """화면에 보낼 모양(행은 10개까지)."""
    return {"ok": result["ok"], "basis": result["basis"], "columns": result["columns"],
            "rows": result["rows"][:10], "total": len(result["rows"]), "sql": result["sql"], "error": result["error"]}


# 의도 판단용(규칙 쪽에서 가져다 쓴다)
def dumps(result: dict) -> str:
    return json.dumps(public(result), ensure_ascii=False)
