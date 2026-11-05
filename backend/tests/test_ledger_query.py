"""자유 질문 SQL 검사기 점검. DB 없이 돈다.

실행: backend 폴더에서  python -m pytest tests  (pytest 가 없으면  python tests/test_ledger_query.py)
위험한 쿼리가 하나라도 통과하면 실패한다. 새 우회 수법을 알게 되면 BAD 에 한 줄 추가한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ledger_query import QueryRejected, validate_sql  # noqa: E402

GOOD = [
    "SELECT SUM(amount) AS 합계 FROM spending WHERE TO_CHAR(date,'YYYY-MM')='2026-11'",
    "SELECT EXTRACT(DOW FROM date) AS 요일, SUM(amount) FROM spending GROUP BY 1 ORDER BY 2 DESC",
    "WITH m AS (SELECT category, SUM(amount) s FROM spending GROUP BY 1) SELECT * FROM m ORDER BY s DESC LIMIT 3",
    "SELECT category FROM spending WHERE amount > (SELECT AVG(amount) FROM spending)",
    "SELECT CASE EXTRACT(DOW FROM date) WHEN 0 THEN '일' WHEN 1 THEN '월' ELSE '기타' END AS 요일, SUM(amount) FROM spending GROUP BY 1",
    "SELECT m.month, c.category, c.amount FROM monthly_budgets m JOIN category_limits c ON c.month = m.month",
]

BAD = [
    "DELETE FROM spending",
    "UPDATE monthly_budgets SET total_amount = 1",
    "INSERT INTO income VALUES (1)",
    "DROP TABLE spending",
    "SELECT * FROM members",                                  # 허용 목록 밖의 표
    "SELECT password_hash FROM members",
    "SELECT * FROM card_transactions",                        # 원본 표 직접 접근
    "SELECT * FROM public.spending",                          # 스키마 지정
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM information_schema.tables",
    "SELECT set_config('app.member_id', 'other', false)",     # 설정 바꾸기
    "SELECT current_setting('server_version')",
    "SELECT pg_sleep(10)",                                    # 서버 붙잡기
    "SELECT version()",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT 1; DELETE FROM spending",                         # 문장 이어 붙이기
    "SELECT * FROM spending s JOIN members m ON true",
    "WITH spending AS (SELECT 1) SELECT * FROM spending",     # 가상 표 이름 가로채기
    "SELECT * INTO tmp FROM spending",
    "SELECT * FROM spending FOR UPDATE",
    "",
]


def test_good_pass():
    for sql in GOOD:
        validate_sql(sql, "member_001")


def test_bad_rejected():
    leaked = []
    for sql in BAD:
        try:
            validate_sql(sql, "member_001")
            leaked.append(sql)
        except QueryRejected:
            pass
    assert not leaked, "통과하면 안 되는 쿼리가 통과했다:\n" + "\n".join(leaked)


if __name__ == "__main__":
    test_good_pass()
    test_bad_rejected()
    print(f"ok ({len(GOOD)} good, {len(BAD)} bad)")
