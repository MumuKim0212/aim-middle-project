"""models.py 의 테이블·컬럼이 DB 문서와 맞는지 대조한다 (코드는 import 하지 않고 ast 로만 읽는다).

검사
  1. 문서 어디에도 나오지 않는 테이블
  2. 컬럼 표(`| 컬럼 |` 머리글)가 있는 절: 표에만 있는 컬럼, 모델에만 있는 컬럼
     절 제목에 모델 테이블 이름이 들어 있어야 대응시킨다 (예: `### 7.2 accounts (계좌)`)
기본은 경고만 출력하고 0 으로 끝난다. 막으려면 --strict 또는 환경 변수 DOCCHECK_STRICT=1.
shortcut: 컬럼 표가 없는 서술형 문서(db-design 의 `a · b · c` 나열 등)는 컬럼 단위로 보지 않는다, 표로 바뀌면 자동으로 검사 대상이 된다.
"""
import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "backend" / "app" / "models.py"
DOCS = [ROOT / "docs" / p for p in (
    "db/db-design.md", "db/erd.md", "dev/auth/backend-spec.md", "dev/account/backend-spec.md", "dev/card/backend-spec.md")]


def model_tables() -> dict[str, set[str]]:
    tables = {}
    for node in ast.parse(MODELS.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.ClassDef):
            continue
        name, cols = None, set()
        for st in node.body:
            if isinstance(st, ast.Assign) and any(getattr(t, "id", "") == "__tablename__" for t in st.targets):
                name = st.value.value
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                cols.add(st.target.id)
        if name:
            tables[name] = cols
    return tables


def doc_sections(path: Path):
    """(제목, 컬럼 표의 첫 칸 식별자 집합) 목록. 컬럼 표가 없는 절은 빈 집합."""
    out, title, cols, in_col_table = [], "", set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            out.append((title, cols))
            title, cols, in_col_table = line, set(), False
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            first = cells[0].strip("` ")
            if first in ("컬럼", "column"):
                in_col_table = True
            elif in_col_table and not set(first) <= set("-: "):
                for ident in re.split(r"\s*/\s*", cells[0]):
                    ident = ident.strip("` ")
                    if re.fullmatch(r"[a-z][a-z0-9_]*", ident):
                        cols.add(ident)
        else:
            in_col_table = False if not line.strip() else in_col_table
    out.append((title, cols))
    return out


def main() -> int:
    tables = model_tables()
    warnings = []
    alltext = "\n".join(p.read_text(encoding="utf-8") for p in DOCS if p.exists())
    for t in tables:
        if not re.search(rf"(?<![a-z_]){t}(?![a-z_])", alltext):
            warnings.append(f"문서에 없는 테이블: {t}")
    for path in DOCS:
        if not path.exists():
            continue
        for title, doc_cols in doc_sections(path):
            if not doc_cols:
                continue
            hits = [t for t in tables if re.search(rf"(?<![a-z_]){t}(?![a-z_])", title)]
            if not hits:
                continue
            t = max(hits, key=lambda x: len(doc_cols & tables[x]))  # 제목에 테이블이 둘이면 컬럼이 더 겹치는 쪽
            rel = path.relative_to(ROOT).as_posix()
            for c in sorted(doc_cols - tables[t]):
                warnings.append(f"{rel} [{title.lstrip('# ')}]: 문서에만 있는 컬럼 {t}.{c}")
            for c in sorted(tables[t] - doc_cols):
                warnings.append(f"{rel} [{title.lstrip('# ')}]: 모델에만 있는 컬럼 {t}.{c}")
    for w in warnings:
        print("DOCCHECK", w)
    print(f"DOCCHECK 모델 테이블 {len(tables)}개 검사, 차이 {len(warnings)}건")
    strict = "--strict" in sys.argv or os.environ.get("DOCCHECK_STRICT") == "1"
    return 1 if (warnings and strict) else 0


if __name__ == "__main__":
    sys.exit(main())
