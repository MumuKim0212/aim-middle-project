"""[역할] backend/app/loan/schema.sql의 @domain/@ext 태그와 PK·FK를 읽어 전체 개요 ERD와 영역별 상세 ERD를 PNG로 그린다."""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[2] / "backend" / "app" / "loan" / "schema.sql"
OUT = HERE

# ---------------------------------------------------------------- 글꼴·색
for f in ("C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"):
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

DOMAINS = ["기준정보", "신청·심사", "약정·실행", "정부·기관", "대환", "대출관리", "보안·감사"]
DCOLOR = {"기준정보": "#5B7DB1", "신청·심사": "#2E8B8B", "약정·실행": "#3A7D44", "정부·기관": "#8C6BB1",
          "대환": "#C06C2B", "대출관리": "#B5465A", "보안·감사": "#555F6D"}
EXTS = ["회원·개인정보", "로그인·인증", "은행(계좌)", "카드", "메인 화면"]
ECOLOR = "#E8A33D"
INK, MUTED, LINE = "#1F2933", "#6B7785", "#9AA5B1"


# ---------------------------------------------------------------- 파서
def parse(path: Path = SCHEMA) -> dict:
    """테이블 → {domain, cols:[{name,type,pk,fk,ext,note}]}."""
    tables: dict[str, dict] = {}
    domain, cur = None, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = re.match(r"--\s*@domain\s+(.+)", line)
        if m:
            domain = m.group(1).split(" (")[0].strip()
            continue
        m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", line)
        if m:
            cur = m.group(1)
            tables[cur] = {"domain": domain, "cols": []}
            continue
        if cur is None:
            continue
        if line.startswith(");"):
            cur = None
            continue
        code, _, comment = line.partition("--")
        code = code.strip().rstrip(",")
        m = re.match(r"PRIMARY KEY\s*\(([^)]+)\)", code)
        if m:
            for c in m.group(1).split(","):
                for col in tables[cur]["cols"]:
                    if col["name"] == c.strip():
                        col["pk"] = True
            continue
        m = re.match(r"FOREIGN KEY\s*\((\w+)\)\s*REFERENCES\s+(\w+)\((\w+)\)", code)
        if m:
            for col in tables[cur]["cols"]:
                if col["name"] == m.group(1):
                    col["fk"] = (m.group(2), m.group(3))
            continue
        if not code or code.split()[0].upper() in ("UNIQUE", "CHECK", "CONSTRAINT", "PRIMARY", "FOREIGN"):
            continue
        parts = code.split()
        fk = re.search(r"REFERENCES\s+(\w+)\((\w+)\)", code)
        ext = re.search(r"@ext\s+(\S+)", comment)
        tables[cur]["cols"].append({"name": parts[0], "type": parts[1] if len(parts) > 1 else "",
                                    "pk": "PRIMARY KEY" in code.upper(), "fk": (fk.group(1), fk.group(2)) if fk else None,
                                    "ext": ext.group(1) if ext else None})
    return tables


def short_type(t: str) -> str:
    t = t.upper()
    for k, v in (("VARCHAR", "TEXT"), ("NUMERIC", "NUM"), ("TIMESTAMPTZ", "TS"), ("BIGINT", "BIGINT"), ("INTEGER", "INT"), ("JSONB", "JSON"), ("DATE", "DATE"), ("BOOLEAN", "BOOL")):
        if t.startswith(k):
            return v
    return t[:6]


# ---------------------------------------------------------------- 그리기 도우미
def box(ax, x, y, w, h, fc, ec, lw=1.2, ls="-", r=0.08, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls, zorder=z))


def arrow(ax, p, q, color=LINE, ls="-", lw=1.1, rad=0.0, label=None, z=1, fs=8):
    ax.annotate("", xy=q, xytext=p, zorder=z,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, ls=ls, shrinkA=2, shrinkB=2, mutation_scale=11,
                                connectionstyle=f"arc3,rad={rad}"))
    if label:
        dx, dy = q[0] - p[0], q[1] - p[1]           # arc3 곡선의 실제 중간점(2차 베지어 t=0.5)에 라벨을 둔다
        ax.text((p[0] + q[0]) / 2 + 0.5 * rad * dy, (p[1] + q[1]) / 2 - 0.5 * rad * dx, label, fontsize=fs, color=color, ha="center", va="center", zorder=5,
                bbox=dict(fc="white", ec="none", pad=1.2))


def ext_columns(tables) -> dict[str, list[tuple[str, str, str]]]:
    out = defaultdict(list)
    for t, info in tables.items():
        for c in info["cols"]:
            if c["ext"]:
                out[c["ext"]].append((info["domain"], t, c["name"]))
    return out


# ---------------------------------------------------------------- 1) 전체 개요
def _side_points(r1, r2):
    """두 상자 중심의 상대 위치로 마주 보는 변의 중점을 고른다."""
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    c1, c2 = (x1 + w1 / 2, y1 + h1 / 2), (x2 + w2 / 2, y2 + h2 / 2)
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    if abs(dx) / (w1 / 2 + w2 / 2) >= abs(dy) / (h1 / 2 + h2 / 2):
        return ((x1 + w1, c1[1]), (x2, c2[1])) if dx > 0 else ((x1, c1[1]), (x2 + w2, c2[1]))
    return ((c1[0], y1 + h1), (c2[0], y2)) if dy > 0 else ((c1[0], y1), (c2[0], y2 + h2))


def overview(tables, path: Path) -> None:
    """위: 외부 서비스 5개(점선 큰 상자) / 가운데: 외부와 닿는 영역 4개 / 아래: 내부 전용 영역 3개."""
    by_dom = defaultdict(list)
    for t, info in tables.items():
        by_dom[info["domain"]].append(t)
    ext = ext_columns(tables)
    W = 36.0
    ew, eh, egap = 6.4, 3.9, 0.6
    bw = 6.4
    row1 = ["신청·심사", "약정·실행", "대출관리", "기준정보"]
    row2 = ["보안·감사", "정부·기관", "대환"]
    eorder = ["회원·개인정보", "로그인·인증", "은행(계좌)", "카드", "메인 화면"]
    hgt = {d: 1.05 + 0.36 * len(by_dom[d]) for d in DOMAINS}
    top = 0.0                                    # 위에서부터 음수 좌표로 쌓고 마지막에 범위를 잡는다
    ey = top - 2.2 - eh
    r1_top = ey - 3.0
    r2_top = r1_top - max(hgt[d] for d in row1) - 3.0
    bottom = r2_top - max(hgt[d] for d in row2) - 1.4
    fig, ax = plt.subplots(figsize=(W * 0.55, (top - bottom) * 0.55), dpi=150)
    ax.set_xlim(0, W)
    ax.set_ylim(bottom, top)
    ax.axis("off")
    ax.text(W / 2, top - 0.2, "대출 서비스 DB 전체 구조 (개요 ERD)", ha="center", va="top", fontsize=21, weight="bold", color=INK)
    ax.text(W / 2, top - 1.15, "주황 점선 = 다른 파트(회원·계좌·카드)와 잇는 논리 참조 칸(FK 없이 id 값만 저장, 공통.md 6장)   ·   회색 실선 = 대출 서비스 안의 영역 간 FK(개수)",
            ha="center", va="top", fontsize=11.5, color=MUTED)

    # 외부 서비스 상자
    future = {"회원·개인정보": "users (BIGINT id)", "로그인·인증": "auth_session · e_sign (예정)",
              "은행(계좌)": "accounts · transactions (BIGINT id)", "카드": "cards (예정)", "메인 화면": "홈 대시보드 (예정)"}
    ex0 = (W - (5 * ew + 4 * egap)) / 2
    ebox = {}
    for i, e in enumerate(eorder):
        x = ex0 + i * (ew + egap)
        ebox[e] = (x, ey, ew, eh)
        box(ax, x, ey, ew, eh, "#FFF6E8", ECOLOR, lw=2.2, ls=(0, (5, 3)), r=0.2)
        ax.text(x + ew / 2, ey + eh - 0.25, e, ha="center", va="top", fontsize=14.5, weight="bold", color="#9A5B00", zorder=3)
        ax.text(x + ew / 2, ey + eh - 0.9, future[e], ha="center", va="top", fontsize=9, color=MUTED, zorder=3)
        lines = (["대출 테이블을 읽기만 함(조회 API)", "· loan_account → 내 대출 요약", "· product_catalog → 상품 목록",
                  "· notification → 알림", "로그인 회원의 user_id로 조회"] if e == "메인 화면"
                 else ["연결할 빈 칸 (테이블.컬럼)"] + ["· " + s for s in sorted({f"{t}.{c}" for _, t, c in ext[e]})])
        for k, s in enumerate(lines):
            first = k == 0
            ax.text(x + 0.3, ey + eh - 1.45 - 0.36 * k, s, fontsize=8.6 if first else 8.8,
                    color="#9A5B00" if first else INK, va="center", zorder=3)

    # 영역 블록
    rects = {}

    def place(row, y_top):
        gap = (W - 1.2 - len(row) * bw) / (len(row) - 1)
        for i, d in enumerate(row):
            x = 0.6 + i * (bw + gap)
            h = hgt[d]
            y = y_top - h
            names = sorted(by_dom[d])
            box(ax, x, y, bw, h, "white", DCOLOR[d], lw=2)
            box(ax, x, y + h - 0.8, bw, 0.8, DCOLOR[d], DCOLOR[d], lw=2)
            ax.text(x + bw / 2, y + h - 0.4, f"{d}  ({len(names)})", ha="center", va="center", color="white", fontsize=13, weight="bold", zorder=3)
            for k, n in enumerate(names):
                ax.text(x + 0.35, y + h - 1.1 - 0.36 * k, n, va="center", fontsize=9.5, color=INK, zorder=3)
            rects[d] = (x, y, bw, h)

    place(row1, r1_top)
    place(row2, r2_top)

    # 외부 연결: 블록 윗변 → 외부 상자 아랫변 (출발·도착 지점을 나눠 겹치지 않게)
    links = [(d, e) for e in eorder[:4] for d in row1 if any(dd == d for dd, _, _ in ext[e])]
    links += [("대출관리", "메인 화면"), ("기준정보", "메인 화면")]
    out_n = defaultdict(list)
    in_n = defaultdict(list)
    for d, e in links:
        out_n[d].append(e)
        in_n[e].append(d)
    for d, e in links:
        x, y, w, h = rects[d]
        i, n = out_n[d].index(e), len(out_n[d])
        p = (x + w * (i + 1) / (n + 1), y + h)
        X, Y, Wd, _ = ebox[e]
        j, m = in_n[e].index(d), len(in_n[e])
        q = (X + Wd * (j + 1) / (m + 1), Y)
        arrow(ax, p, q, color=ECOLOR, ls=(0, (4, 3)), lw=1.8, z=1)

    # 영역 간 FK
    cross = defaultdict(int)
    for t, info in tables.items():
        for c in info["cols"]:
            if c["fk"] and c["fk"][0] in tables:
                a, b = info["domain"], tables[c["fk"][0]]["domain"]
                if a != b:
                    cross[(a, b)] += 1
    for (a, b), n in sorted(cross.items()):
        ra, rb = rects[a], rects[b]
        same_row = abs((ra[1] + ra[3]) - (rb[1] + rb[3])) < 0.01 or (a in row1) == (b in row1)
        if same_row and a in row1:
            ia, ib = row1.index(a), row1.index(b)
            if abs(ia - ib) == 1:
                yy = ra[1] + ra[3] - 1.4 - (0.5 if ia < ib else 1.2)
                p = (ra[0] + ra[2], yy) if ia < ib else (ra[0], yy)
                q = (rb[0], yy) if ia < ib else (rb[0] + rb[2], yy)
                arrow(ax, p, q, color="#7B8794", lw=1.3, label=f"FK {n}", fs=8.5)
            else:                                 # 떨어진 블록: 아래로 돌아감
                p = (ra[0] + ra[2] * (0.35 if ia < ib else 0.65), ra[1])
                q = (rb[0] + rb[2] * (0.35 if ia > ib else 0.65), rb[1])
                arrow(ax, p, q, color="#7B8794", lw=1.3, rad=0.25 if ia < ib else -0.25, label=f"FK {n}", fs=8.5)
        elif same_row:
            ia, ib = row2.index(a), row2.index(b)
            p = (ra[0] + ra[2], ra[1] + ra[3] / 2) if ia < ib else (ra[0], ra[1] + ra[3] / 2)
            q = (rb[0], rb[1] + rb[3] / 2) if ia < ib else (rb[0] + rb[2], rb[1] + rb[3] / 2)
            arrow(ax, p, q, color="#7B8794", lw=1.3, label=f"FK {n}", fs=8.5)
        else:
            lo, hi = (ra, rb) if a in row2 else (rb, ra)
            k_lo = row2.index(a if a in row2 else b)
            k_hi = row1.index(b if a in row2 else a)
            p_lo = (lo[0] + lo[2] * (0.2 + 0.2 * k_hi), lo[1] + lo[3])
            p_hi = (hi[0] + hi[2] * (0.25 + 0.25 * k_lo), hi[1])
            p, q = (p_lo, p_hi) if a in row2 else (p_hi, p_lo)
            arrow(ax, p, q, color="#7B8794", lw=1.3, label=f"FK {n}", fs=8.5)

    ax.text(0.6, bottom + 0.4, "※ 외부 칸은 다른 파트 테이블의 id 값을 그대로 저장한다(FK 없음, 공통.md 6장).  화살표 방향 = 참조하는 쪽 → 참조되는 쪽.  생성: docs/loan/erd/make_erd.py (schema.sql 태그 기준)",
            fontsize=9.5, color=MUTED)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 2) 영역별 상세
def detail(tables, domain: str, path: Path) -> None:
    names = [t for t, i in tables.items() if i["domain"] == domain]
    ncol = 4 if len(names) > 6 else 3
    bw, rh, hh, gx, gy = 4.3, 0.29, 0.62, 1.5, 0.9
    heights = {t: hh + rh * len(tables[t]["cols"]) + 0.12 for t in names}
    # 열 우선 배치(열 높이 균형)
    cols_list = [[] for _ in range(ncol)]
    col_h = [0.0] * ncol
    for t in names:
        k = col_h.index(min(col_h))
        cols_list[k].append(t)
        col_h[k] += heights[t] + gy
    foreign = sorted({c["fk"][0] for t in names for c in tables[t]["cols"] if c["fk"] and c["fk"][0] in tables and tables[c["fk"][0]]["domain"] != domain})
    exts = sorted({c["ext"] for t in names for c in tables[t]["cols"] if c["ext"]}, key=EXTS.index)
    top_band = 2.6 if exts else 0.6
    W = ncol * (bw + gx) + (3.6 if foreign else 0) + 0.6
    H = max(col_h) + top_band + 1.6
    fig, ax = plt.subplots(figsize=(W * 0.55, H * 0.55), dpi=150)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    ax.text(0.3, H - 0.3, f"{domain} 상세 ERD", fontsize=17, weight="bold", color=DCOLOR[domain], va="top")
    ax.text(0.3, H - 0.95, "PK 기본키 · FK 외래키(실선 화살표) · EXT 외부 서비스 연결 빈 칸(주황 점선, 통합 때 연결) · 회색 점선 상자 = 다른 영역 테이블",
            fontsize=9, color=MUTED, va="top")
    geo = {}
    for k, col in enumerate(cols_list):
        y = H - top_band - 1.3
        x = 0.4 + k * (bw + gx)
        for t in col:
            h = heights[t]
            geo[t] = (x, y - h, bw, h)
            y -= h + gy
    rowy = {}
    for t, (x, y, w, h) in geo.items():
        box(ax, x, y, w, h, "white", DCOLOR[domain], lw=1.6)
        box(ax, x, y + h - hh, w, hh, DCOLOR[domain], DCOLOR[domain], lw=1.6)
        ax.text(x + w / 2, y + h - hh / 2, t, ha="center", va="center", color="white", fontsize=10.5, weight="bold", zorder=3)
        for i, c in enumerate(tables[t]["cols"]):
            cy = y + h - hh - rh * (i + 0.5) - 0.04
            rowy[(t, c["name"])] = cy
            tag = "PK" if c["pk"] else ""
            if c["fk"]:
                tag = "PK·FK" if tag else "FK"
            if c["ext"]:
                tag = "EXT"
            color = "#9A5B00" if c["ext"] else INK
            ax.text(x + 0.1, cy, tag, fontsize=6.6, color=DCOLOR[domain] if tag != "EXT" else ECOLOR, weight="bold", va="center", zorder=3)
            ax.text(x + 0.9, cy, c["name"], fontsize=8.2, color=color, va="center", zorder=3, weight="bold" if c["pk"] else "normal")
            ax.text(x + w - 0.1, cy, short_type(c["type"]), fontsize=7, color=MUTED, va="center", ha="right", zorder=3)
    # 다른 영역 테이블(유령 상자)
    fx = ncol * (bw + gx) + 0.3
    for i, f in enumerate(foreign):
        y = H - top_band - 1.3 - 1.0 - i * 1.15
        geo[f] = (fx, y, 3.2, 0.75)
        fd = tables[f]["domain"]
        box(ax, fx, y, 3.2, 0.75, "#F5F7FA", LINE, lw=1.2, ls=(0, (3, 2)))
        ax.text(fx + 1.6, y + 0.48, f, ha="center", va="center", fontsize=9, color=INK, zorder=3)
        ax.text(fx + 1.6, y + 0.18, f"[{fd}]", ha="center", va="center", fontsize=7.5, color=DCOLOR.get(fd, MUTED), zorder=3)
    # 외부 서비스 상자(위쪽 띠)
    egeo = {}
    for i, e in enumerate(exts):
        ew = 4.0
        ex = 0.4 + i * (ew + 0.8)
        ey = H - top_band - 0.15 - 0.2
        egeo[e] = (ex, ey, ew, 1.25)
        box(ax, ex, ey, ew, 1.25, "#FFF6E8", ECOLOR, lw=2, ls=(0, (5, 3)), r=0.15)
        ax.text(ex + ew / 2, ey + 0.8, e, ha="center", va="center", fontsize=11.5, weight="bold", color="#9A5B00", zorder=3)
        ax.text(ex + ew / 2, ey + 0.35, "외부 서비스 (테이블 미생성)", ha="center", va="center", fontsize=7.5, color=MUTED, zorder=3)
    # FK 화살표
    for t in names:
        x, y, w, h = geo[t]
        for c in tables[t]["cols"]:
            if c["fk"] and c["fk"][0] in geo and c["fk"][0] != t:
                tx, ty, tw, th = geo[c["fk"][0]]
                sy = rowy[(t, c["name"])]
                if tx > x + 0.1:
                    p, q = (x + w, sy), (tx, ty + th - 0.3)
                elif tx < x - 0.1:
                    p, q = (x, sy), (tx + tw, ty + th - 0.3)
                else:                                  # 같은 열: 오른쪽으로 돌아 들어감
                    p, q = (x + w, sy), (tx + tw, ty + th - 0.3)
                    arrow(ax, p, q, color="#52606D", rad=-0.45, lw=1.0)
                    continue
                arrow(ax, p, q, color="#52606D", rad=0.06, lw=1.0)
            if c["ext"]:
                ex, ey, ew, eh = egeo[c["ext"]]
                arrow(ax, (x + w * 0.62, rowy[(t, c["name"])]), (ex + ew / 2, ey), color=ECOLOR, ls=(0, (4, 3)), lw=1.3, rad=0.1)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tables = parse()
    OUT.mkdir(parents=True, exist_ok=True)
    unknown = sorted({i["domain"] for i in tables.values()} - set(DOMAINS))
    if unknown:
        print("알 수 없는 도메인:", unknown)
        return 1
    overview(tables, OUT / "00_전체_개요_ERD.png")
    for k, d in enumerate(DOMAINS, 1):
        detail(tables, d, OUT / f"{k:02d}_{d.replace('·', '_')}_ERD.png")
    n_fk = sum(1 for i in tables.values() for c in i["cols"] if c["fk"])
    n_ext = sum(1 for i in tables.values() for c in i["cols"] if c["ext"])
    print(f"테이블 {len(tables)}개 · FK {n_fk}개 · 외부 연결 칸 {n_ext}개 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
