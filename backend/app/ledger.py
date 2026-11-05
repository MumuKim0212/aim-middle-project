"""가계부 API (박의혁).

기준: 가계부_4가지_모드_체험.html 의 계산식을 서버로 옮긴 것. 금액은 전부 정수(원).
member_id 는 인증 세션(current_member)에서만 얻는다.

사용 테이블 (docs/db/db-design.md 5절, 변경 없음)
  card_transactions + ledger_tx_category : 월 지출 / 카테고리별 지출
  budgets + category_budgets             : 월 예산 / 카테고리 예산
  planned_outflows                       : 예정 출금(카드대금) → 예상 잔액
  payment_attempts                       : 결제 전 확인 기록
  ledger_settings                        : 말투·화면 모드

계산
  순지출        = 승인 합계 - 취소 합계 (취소는 원 승인 거래의 카테고리를 따른다)
  남은 예산     = 월 예산 - 순지출
  예상 잔액     = 대표계좌 잔액 - 예정 출금 합계
  위험 단계     = danger : 월 예산/카테고리 예산/예상 잔액 중 하나라도 0 이하
                  caution: 사용률 75% 이상, 또는 카테고리 예산 사용률 80% 이상
                  safe   : 그 외
  결제 전 확인  = 금액이 월 예산 잔여 / 예상 잔액 / 카테고리 예산 잔여 중 하나라도 넘으면 보류
"""
import base64
import csv
import dataclasses
import io
import json
import re
import statistics
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import ledger_categorize, ledger_query
from . import models as m
from .db import SessionLocal, engine, get_db
from .deps import current_member
from .ledger_answer import enabled as answer_enabled, generate_answer, stream_answer
from .gemini import LlmUnavailable, generate_json_image
from .ledger_nlu import find_category_hint, income_source, is_record_command, parse_days_ago, understand

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
UNCATEGORIZED = "기타"
CATEGORIES = ["배달", "외식", "장보기", "쇼핑", "교통", "생활", "기타"]
MODES = ("roast", "basic", "kind", "numbers")


def this_month() -> str:
    return date.today().strftime("%Y-%m")


def pct(part: int, whole: int) -> int:
    """정수 퍼센트, 반올림은 half-up (시안의 JS Math.round 와 같다)."""
    return (part * 100 + whole // 2) // whole if whole else 0


def month_range(month: str) -> tuple[date, date]:
    if not MONTH_RE.match(month):
        raise HTTPException(400, "INVALID_MONTH")
    y, mo = int(month[:4]), int(month[5:])
    return date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1)


def category_spent(db: Session, member_id: str, start: date, end: date) -> dict[str, int]:
    """카테고리별 순지출. 취소 거래는 원 승인 거래의 카테고리를 따른다."""
    signed = case((m.CardTransaction.kind == "approval", m.CardTransaction.amount),
                  else_=-m.CardTransaction.amount)
    cat = func.coalesce(m.LedgerTxCategory.category, UNCATEGORIZED).label("cat")
    rows = db.execute(
        select(cat, func.sum(signed))
        .select_from(m.CardTransaction)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(
            m.LedgerTxCategory,
            m.LedgerTxCategory.card_transaction_id == func.coalesce(m.CardTransaction.original_id, m.CardTransaction.id),
        )
        .where(m.Card.member_id == member_id,
               m.CardTransaction.occurred_at >= start,
               m.CardTransaction.occurred_at < end)
        .group_by(cat)
    ).all()
    return {name: int(total) for name, total in rows}


def _examples(db: Session, member_id: str, budget_remaining: int, budget_set: bool) -> dict:
    """화면의 예시 금액(질문 칩·입력칸 예시·시뮬레이션 버튼)도 DB 에서 계산한다. 화면에 금액을 박아 두지 않는다.

    typical : 배달 한 번에 쓰는 평소 금액(최근 3개월 배달 승인 거래의 평균, 천 원 단위). 거래가 없으면 10,000원.
    large   : 월 예산 남은 금액을 넘는 큰 금액(결제 보류를 보여 주는 시뮬레이션용). 예산이 없으면 100,000원.
    """
    today = date.today()
    y, mo = divmod(today.year * 12 + today.month - 1 - 2, 12)
    since = date(y, mo + 1, 1)
    avg = db.scalar(
        select(func.avg(m.CardTransaction.amount))
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .join(m.LedgerTxCategory, m.LedgerTxCategory.card_transaction_id == m.CardTransaction.id)
        .where(m.Card.member_id == member_id, m.CardTransaction.kind == "approval",
               m.LedgerTxCategory.category == "배달", m.CardTransaction.occurred_at >= since)
    )
    typical = max(1000, int(round(float(avg) / 1000)) * 1000) if avg else 10_000
    large = ((max(budget_remaining, 0) // 10_000) + 1) * 10_000 if budget_set else 100_000
    return {"category": "배달", "typical": typical, "large": large}


def _income(db: Session, member_id: str, start: date, end: date) -> int:
    """그 기간에 내 계좌로 들어온 돈(입금·이체 입금). 대출 실행금은 수입으로 보지 않는다."""
    total = db.scalar(
        select(func.coalesce(func.sum(m.AccountTransaction.amount), 0))
        .join(m.Account, m.Account.id == m.AccountTransaction.account_id)
        .where(m.Account.member_id == member_id, m.AccountTransaction.kind.in_(("deposit", "transfer_in")),
               m.AccountTransaction.occurred_at >= datetime.combine(start, time.min),
               m.AccountTransaction.occurred_at < datetime.combine(end, time.min)))
    return int(total or 0)


def _goal(db: Session, member_id: str, month: str, saved_amount: int) -> dict | None:
    g = db.scalar(select(m.LedgerGoal).where(m.LedgerGoal.member_id == member_id, m.LedgerGoal.month == month))
    if not g:
        return None
    weeks = -(-(month_range(month)[1] - month_range(month)[0]).days // 7)  # 그 달의 주 수(올림)
    monday = date.today() - timedelta(days=date.today().weekday())
    week_saved = _saved(db, member_id, max(monday, month_range(month)[0]))["heldAmount"]
    return {"name": g.name, "target": g.target_amount, "saved": saved_amount,
            "ratio": min(100, pct(saved_amount, g.target_amount)),
            "weeklyTarget": -(-g.target_amount // weeks), "weekSaved": week_saved}


def _forecast(spent: int, total: int, month: str) -> dict | None:
    """이번 달 소비 속도로 월말 지출과 예산 소진일을 예측한다. 이번 달이 아니면 None."""
    today = date.today()
    if month != this_month():
        return None
    first, nxt = month_range(month)
    days_in_month = (nxt - first).days
    avg = spent / today.day if today.day else 0
    projected = int(round(avg * days_in_month))
    over = total > 0 and spent >= total
    run_out = None
    if total > 0 and not over and avg > 0 and projected > total:
        run_out = min(days_in_month, -(-total // max(1, int(avg))))  # 올림
        run_out = max(run_out, min(days_in_month, today.day + 1))
    return {"dailyAvg": int(round(avg)), "projected": projected, "runOutDay": run_out,
            "daysLeft": days_in_month - today.day, "over": over}


def _saved(db: Session, member_id: str, start: date) -> dict:
    """결제 전 확인에서 '보류'가 나온 이번 달 시도: 횟수와 합계 금액."""
    count, total = db.execute(
        select(func.count(m.PaymentAttempt.id), func.coalesce(func.sum(m.PaymentAttempt.amount), 0))
        .where(m.PaymentAttempt.member_id == member_id, m.PaymentAttempt.result == "held",
               m.PaymentAttempt.created_at >= datetime.combine(start, time.min))
    ).one()
    return {"heldCount": int(count), "heldAmount": int(total)}


def _streak(db: Session, member_id: str) -> int:
    """오늘부터 거꾸로 세는 무지출 연속 일수(카드 승인이 없는 날). 오늘 쓴 게 있으면 0."""
    since = date.today() - timedelta(days=60)
    rows = db.execute(
        select(m.CardTransaction.occurred_at)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .where(m.Card.member_id == member_id, m.CardTransaction.kind == "approval",
               m.CardTransaction.occurred_at >= datetime.combine(since, time.min))).all()
    spent_days = {r[0].date() for r in rows}
    n, day = 0, date.today()
    while day >= since and day not in spent_days:
        n += 1
        day -= timedelta(days=1)
    return n


def ensure_month_budget(db: Session, member_id: str, month: str) -> None:
    """이번 달 예산이 아직 없으면 가장 최근 달의 예산(월 예산 + 분류 예산)을 이어받아 만든다. 새 달에도 경고·예측이 꺼지지 않게."""
    if db.scalar(select(m.Budget.id).where(m.Budget.member_id == member_id, m.Budget.month == month)):
        return
    prev = db.scalar(select(m.Budget).where(m.Budget.member_id == member_id, m.Budget.month < month)
                     .order_by(m.Budget.month.desc()))
    if not prev:
        return
    try:
        new = m.Budget(member_id=member_id, month=month, total_amount=prev.total_amount, emergency_floor=prev.emergency_floor)
        db.add(new)
        db.flush()
        for c in db.scalars(select(m.CategoryBudget).where(m.CategoryBudget.budget_id == prev.id)):
            db.add(m.CategoryBudget(budget_id=new.id, category=c.category, amount=c.amount))
        db.commit()
    except IntegrityError:  # 동시에 두 요청이 만들려 한 경우: 이미 만들어진 것을 쓴다
        db.rollback()


def _daily(db: Session, member_id: str, remaining: int, month: str) -> dict | None:
    """오늘 쓸 수 있는 돈 = (오늘 아침 기준 남은 예산) ÷ (오늘 포함 남은 일수). 이번 달만."""
    if month != this_month():
        return None
    today = date.today()
    first, nxt = month_range(month)
    days_left = (nxt - first).days - today.day + 1
    spent_today = sum(category_spent(db, member_id, today, today + timedelta(days=1)).values())
    base = remaining + spent_today  # 오늘 쓰기 전의 남은 예산
    allowance = max(0, base // days_left) if base > 0 else 0
    return {"allowance": allowance, "todaySpent": spent_today, "left": allowance - spent_today, "daysLeft": days_left}


def build_summary(db: Session, member_id: str, month: str) -> dict:
    ledger_categorize.ensure_categories(db, member_id)  # 카드 서비스에서 새로 들어온 거래를 자동 분류
    if month == this_month():
        ensure_month_budget(db, member_id, month)
    start, end = month_range(month)
    spent_by_cat = category_spent(db, member_id, start, end)
    spent = sum(spent_by_cat.values())
    saved = _saved(db, member_id, start)

    budget = db.scalar(select(m.Budget).where(m.Budget.member_id == member_id, m.Budget.month == month))
    total = budget.total_amount if budget else 0
    cat_budgets: dict[str, int] = {}
    if budget:
        cat_budgets = {c.category: c.amount for c in db.scalars(
            select(m.CategoryBudget).where(m.CategoryBudget.budget_id == budget.id))}

    categories = []
    for cat in sorted(set(cat_budgets) | set(spent_by_cat), key=lambda c: CATEGORIES.index(c) if c in CATEGORIES else 99):
        s, b = spent_by_cat.get(cat, 0), cat_budgets.get(cat)
        categories.append({
            "category": cat, "budget": b, "spent": s,
            "remaining": None if b is None else b - s,
            "ratio": None if not b else pct(s, b),
            "over": b is not None and s > b,
        })

    primary = db.scalar(select(m.Account).where(
        m.Account.member_id == member_id, m.Account.is_primary.is_(True), m.Account.status == "active"))
    balance = primary.balance if primary else 0
    planned_rows = db.scalars(
        select(m.PlannedOutflow)
        .where(m.PlannedOutflow.member_id == member_id, m.PlannedOutflow.status == "planned",
               m.PlannedOutflow.due_date >= max(date.today(), start), m.PlannedOutflow.due_date < end)
        .order_by(m.PlannedOutflow.due_date)
    ).all()
    planned_total = sum(p.amount for p in planned_rows)
    expected = balance - planned_total

    remaining = total - spent
    ratio = pct(spent, total)
    over_cat = [c for c in categories if c["budget"] is not None and c["remaining"] <= 0]
    hot_cat = [c for c in categories if c["ratio"] is not None and c["ratio"] >= 80]
    if not budget:
        level = "safe"
    elif remaining <= 0 or over_cat or expected <= 0:
        level = "danger"
    elif ratio >= 75 or hot_cat:
        level = "caution"
    else:
        level = "safe"

    return {
        "month": month,
        "budget": {
            "total": total, "spent": spent, "remaining": remaining, "ratio": ratio,
            "emergencyFloor": budget.emergency_floor if budget else 0, "set": budget is not None,
        },
        "risk": {"level": level, "ratio": ratio,
                 "hotCategories": [c["category"] for c in (over_cat + [h for h in hot_cat if h not in over_cat])]},
        "categories": categories,
        "examples": _examples(db, member_id, remaining, budget is not None),
        "forecast": _forecast(spent, total, month),
        "daily": _daily(db, member_id, remaining, month) if budget else None,
        "saved": saved,
        "income": _income(db, member_id, start, end),
        "goal": _goal(db, member_id, month, saved["heldAmount"]),
        "streak": _streak(db, member_id) if month == this_month() else 0,
        "account": None if not primary else {
            "id": primary.id, "bankName": primary.bank_name, "masked": primary.account_masked},
        "balance": {
            "current": balance, "plannedOutflow": planned_total, "expected": expected,
            "planned": [{"id": p.id, "dueDate": p.due_date.isoformat(), "amount": p.amount, "type": p.type}
                        for p in planned_rows],
        },
    }


@router.get("/summary")
def summary(
    month: str = Query(default_factory=this_month),
    member: m.Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    return build_summary(db, member.id, month)


# ───────────── 결제 전 확인 ─────────────


class PaymentCheckIn(BaseModel):
    amount: int = Field(gt=0, le=10_000_000_000)
    category: str = Field(default=UNCATEGORIZED, max_length=20)
    record: bool = True  # False 면 판정만 하고 payment_attempts 에 남기지 않는다(질문창 미리보기)


REASON_ORDER = ("MONTH_BUDGET", "BALANCE", "CATEGORY_BUDGET")


def judge_payment(db: Session, member_id: str, amount: int, category: str, record: bool) -> dict:
    """결제 가능/보류를 서버에서 판정한다. record=True 면 payment_attempts 에 근거를 남긴다."""
    s = build_summary(db, member_id, this_month())
    remaining, expected = s["budget"]["remaining"], s["balance"]["expected"]
    cat = next((c for c in s["categories"] if c["category"] == category and c["budget"] is not None), None)
    cat_remaining = cat["remaining"] if cat else None

    limits = {"MONTH_BUDGET": remaining, "BALANCE": expected, "CATEGORY_BUDGET": cat_remaining}
    reasons = [r for r in REASON_ORDER if limits[r] is not None and amount > limits[r]]
    result = "held" if reasons else "allowed"
    over = max((amount - limits[r] for r in reasons), default=0)

    if record:
        db.add(m.PaymentAttempt(
            member_id=member_id, amount=amount, category=category, result=result,
            reason=reasons[0] if reasons else None, over_amount=over or None))
        db.commit()

    return {
        "result": result,
        "reasons": reasons,
        "limits": limits,
        "overAmount": over,
        "after": {
            "budgetRemaining": remaining - amount,
            "expectedBalance": expected - amount,
            "categoryRemaining": None if cat_remaining is None else cat_remaining - amount,
        },
        "category": category,
        "amount": amount,
    }


@router.post("/payment-check")
def payment_check(
    body: PaymentCheckIn,
    member: m.Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    return judge_payment(db, member.id, body.amount, body.category, body.record)


# ───────────── 물어보기 (대화) ─────────────
#
# 질문 해석은 ledger_nlu.understand(), 계산은 서버 함수로 한다. 대화는 설계서의
# chat_sessions / chat_messages 에 저장한다. 사용자 질문만 한 줄씩 남기고(role='user'),
# 답변 문장은 모드(말투)에 따라 화면에서 만든다. 답변에 쓴 계산 결과는 context_json 에 같이 둔다.

CHAT_KEEP = 24
DEFAULT_CATEGORY = "배달"


def _prev_n_month(n: int) -> str:
    y, mo = date.today().year, date.today().month
    mo -= n
    while mo < 1:
        mo += 12
        y -= 1
    return f"{y:04d}-{mo:02d}"


def _history(db: Session, member_id: str, back: int) -> dict:
    """지난달(back=1) / 지지난달(back=2) 지출과 그 전달 대비."""
    month, before = _prev_n_month(back), _prev_n_month(back + 1)
    cur = category_spent(db, member_id, *month_range(month))
    prior = sum(category_spent(db, member_id, *month_range(before)).values())
    top = max(cur.items(), key=lambda kv: kv[1], default=(None, 0))
    spent = sum(cur.values())
    return {
        "month": month, "spent": spent, "delta": spent - prior, "hasPrior": prior != 0,
        "topName": top[0] if top[1] > 0 else "없음", "topAmount": max(top[1], 0),
    }


REASON_KO = {"MONTH_BUDGET": "월 예산", "BALANCE": "예상 잔액"}


def _week(db: Session, member_id: str) -> dict:
    """이번 주(월요일~오늘) 지출과 지난주 같은 기간 대비."""
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = today + timedelta(days=1)
    cur = category_spent(db, member_id, start, end)
    prior = sum(category_spent(db, member_id, start - timedelta(days=7), end - timedelta(days=7)).values())
    top = max(cur.items(), key=lambda kv: kv[1], default=(None, 0))
    spent = sum(cur.values())
    return {"from": start.isoformat(), "to": today.isoformat(), "spent": spent, "prevSpent": prior,
            "hasPrev": prior != 0, "delta": spent - prior,
            "topName": top[0] if top[1] > 0 else "없음", "topAmount": max(top[1], 0)}


def _cat_spent(db: Session, member_id: str, category: str) -> dict:
    """이번 달 한 분류의 지출과 그 분류 예산(없으면 None)."""
    s = build_summary(db, member_id, this_month())
    row = next((c for c in s["categories"] if c["category"] == category), None)
    return {"category": category, "spent": row["spent"] if row else 0,
            "budget": row["budget"] if row else None, "remaining": row["remaining"] if row else None}


def _entry(msg: m.ChatMessage, replies: list[m.ChatMessage] | None = None) -> dict:
    ctx = msg.context_json or {}
    # 같은 질문에 모드마다 답변이 있을 수 있다(모드를 바꿔 다시 물어본 경우). 모드별로 가장 최근 것을 담는다.
    answers: dict[str, dict] = {}
    for r in replies or []:
        rmode = (r.context_json or {}).get("mode")
        if rmode:
            answers[rmode] = {"text": r.content, "source": (r.context_json or {}).get("source", "llm")}
    return {
        "id": msg.id, "text": msg.content, "intent": msg.intent,
        "amount": ctx.get("amount"), "category": ctx.get("category", DEFAULT_CATEGORY),
        "check": ctx.get("check"), "history": ctx.get("history"),
        "recorded": ctx.get("recorded"), "recordError": ctx.get("recordError"),
        "income": ctx.get("income"), "incomeError": ctx.get("incomeError"),
        "query": ctx.get("query"),
        "week": ctx.get("week"), "catSpent": ctx.get("catSpent"),
        # LLM 이 쓴 답변(검증 통과분)을 모드별로. 화면은 현재 모드의 것만 쓰고, 없으면 현재 모드의 템플릿 문장을 쓴다.
        "answers": answers,
    }


def _answer_facts(intent: str, text: str, ctx: dict, s: dict) -> dict:
    """답변 문장에 쓸 수 있는 사실. 판정과 숫자는 전부 서버가 이미 계산한 값이다.

    항목 이름은 뜻이 분명한 한글로 쓴다(월 예산과 분류 예산, 전체 지출과 분류 지출을 LLM 이 혼동하지 않게).
    질문과 관련 없는 항목은 넣지 않는다. 'verdict' 는 검증용 키다.
    """
    b, bal = s["budget"], s["balance"]
    cat = ctx["category"]
    cat_row = next((c for c in s["categories"] if c["category"] == cat and c["budget"] is not None), None)
    chk, hist = ctx.get("check"), ctx.get("history")

    if hist:  # 지난달·지지난달: 직전 질문의 분류 같은 것은 섞지 않는다
        facts = {
            "verdict": "info", "질문": "지난 달 지출", "조회 월": f"{int(hist['month'][5:])}월",
            "그 달 전체 지출": hist["spent"], "가장 많이 쓴 분류": hist["topName"], "그 분류 지출액": hist["topAmount"],
        }
        if hist.get("hasPrior"):  # 비교할 전달 자료가 있을 때만 증감을 말하게 한다
            facts["전월 대비 증감(+는 더 씀)"] = hist["delta"]
        return facts
    if intent == "record":
        rec = ctx.get("recorded")
        if not rec:  # 금액이 없거나 기록에 실패
            return {"verdict": "info", "질문": "지출 기록", "금액 필요": ctx.get("recordError") is None,
                    "기록 실패": ctx.get("recordError") is not None}
        facts = {
            "verdict": "info", "질문": "지출 기록", "기록한 금액": rec["amount"], "분류": rec["category"],
            "날짜": rec["when"], "기록 후 월 예산 남은 금액": b["remaining"],
        }
        cr = next((c for c in s["categories"] if c["category"] == rec["category"] and c["budget"] is not None), None)
        if cr:
            facts[f"기록 후 {rec['category']} 예산 남은 금액"] = cr["remaining"]
        return facts
    if intent == "query":
        return ledger_query.facts_from(ctx.get("query") or {"ok": False}, text)
    if intent == "income":
        inc = ctx.get("income")
        if not inc:
            return {"verdict": "info", "질문": "수입 기록", "금액 필요": ctx.get("incomeError") is None,
                    "기록 실패": ctx.get("incomeError") is not None}
        return {"verdict": "info", "질문": "수입 기록", "기록한 금액": inc["amount"], "수입 이름": inc["source"],
                "날짜": inc["when"], "기록 후 계좌 잔액": bal["current"], "카드대금 반영 후 예상 잔액": bal["expected"]}
    if intent == "daily":
        d = s.get("daily")
        if not d:
            return {"verdict": "info", "질문": "오늘 쓸 수 있는 돈", "예산 없음": True}
        return {"verdict": "info", "질문": "오늘 쓸 수 있는 돈", "오늘 더 쓸 수 있는 금액": max(0, d["left"]),
                "오늘 이미 쓴 금액": d["todaySpent"], "하루 기준 금액": d["allowance"], "남은 일수": d["daysLeft"],
                "오늘 한도 초과": d["left"] < 0}
    if intent == "week" and ctx.get("week"):
        w = ctx["week"]
        facts = {"verdict": "info", "질문": "이번 주 지출", "이번 주 전체 지출": w["spent"],
                 "가장 많이 쓴 분류": w["topName"], "그 분류 지출액": w["topAmount"]}
        if w["hasPrev"]:
            facts["지난주 같은 기간 대비 증감(+는 더 씀)"] = w["delta"]
        return facts
    if intent == "category" and ctx.get("catSpent"):
        c = ctx["catSpent"]
        facts = {"verdict": "info", "질문": f"이번 달 {c['category']} 지출", "분류": c["category"], "분류 지출": c["spent"]}
        if c["budget"] is not None:
            facts.update({f"{c['category']} 예산": c["budget"], f"{c['category']} 예산 남은 금액": c["remaining"]})
        return facts
    if intent == "balance":
        return {
            "verdict": "info", "질문": "계좌 잔액", "대표계좌 잔액": bal["current"],
            "예정 출금 합계(카드대금 등)": bal["plannedOutflow"], "예정 출금 반영 후 예상 잔액": bal["expected"],
        }
    if intent == "budget":
        facts = {
            "verdict": "info", "질문": "남은 예산", "이번 달 월 예산": b["total"], "이번 달 사용액": b["spent"],
            "월 예산 남은 금액": b["remaining"], "월 예산 사용률": b["ratio"],
        }
        for c in s["categories"]:  # 예산이 있는 분류는 전부(배달만이 아니라)
            if c["budget"] is not None:
                facts.update({f"{c['category']} 예산 남은 금액": c["remaining"], f"{c['category']} 예산 사용률": c["ratio"]})
        return facts

    if intent == "chat":  # 인사·잡담·의도 불명확: 가계부 숫자를 끼워 넣지 않는다
        return {"verdict": "info", "질문": "잡담 또는 의도 불명확", "사용자가 한 말": text}

    # purchase
    if not chk:
        return {"verdict": "info", "질문": "결제 가능 여부", "분류": cat, "금액 필요": True}
    facts = {
        "verdict": chk["result"], "질문": "결제 가능 여부", "판정": "보류" if chk["result"] == "held" else "가능",
        "결제 요청 금액": chk["amount"], "분류": cat,
        "월 예산 남은 금액": b["remaining"], "결제 후 월 예산 남은 금액": chk["after"]["budgetRemaining"],
        "카드대금 반영 후 예상 잔액": bal["expected"], "결제 후 카드대금 반영 예상 잔액": chk["after"]["expectedBalance"],
    }
    if cat_row:
        facts.update({
            f"{cat} 예산 남은 금액": cat_row["remaining"], f"결제 후 {cat} 예산 남은 금액": chk["after"]["categoryRemaining"],
            f"{cat} 예산 사용률": cat_row["ratio"],
        })
    else:
        facts[f"{cat} 예산"] = "설정 없음"  # 분류 예산이 없으면 그 얘기를 하지 말아야 한다
    if chk["result"] == "held":
        facts["보류 사유"] = [f"{cat} 예산 초과" if r == "CATEGORY_BUDGET" else f"{REASON_KO[r]} 초과" for r in chk["reasons"]]
        facts["초과 금액"] = chk["overAmount"]
    return facts


def _mode_session(db: Session, member_id: str, mode: str) -> m.ChatSession | None:
    """이 모드의 가장 최근 대화방. 모드는 방의 첫 메시지(context_json.mode)에 적어 두므로 테이블은 그대로다."""
    sessions = db.scalars(select(m.ChatSession).where(m.ChatSession.member_id == member_id)
                          .order_by(m.ChatSession.created_at.desc(), m.ChatSession.id.desc()).limit(40)).all()
    for sess in sessions:
        first = db.scalar(select(m.ChatMessage).where(m.ChatMessage.session_id == sess.id)
                          .order_by(m.ChatMessage.created_at, m.ChatMessage.id))
        if first and (first.context_json or {}).get("mode") == mode:
            return sess
    return None


def _new_session(db: Session, member_id: str, mode: str) -> m.ChatSession:
    """새 대화방. 빈 방은 모드를 알 수 없으니 첫 메시지로 모드 표시(role='system')를 남긴다."""
    sess = m.ChatSession(member_id=member_id)
    db.add(sess)
    db.flush()
    db.add(m.ChatMessage(session_id=sess.id, role="system", content="새 대화", context_json={"mode": mode}))
    db.commit()
    return sess


def _body_mode(db: Session, member_id: str, mode: str | None) -> str:
    settings = db.get(m.LedgerSettings, member_id)
    return mode if mode in MODES else (settings.mode if settings else "basic")


def _pair(rows: list[m.ChatMessage]) -> list[dict]:
    """시간순 메시지에서 사용자 질문마다 그 답변(assistant)을 짝지어 돌려준다."""
    replies: dict[str, list[m.ChatMessage]] = {}
    for r in rows:
        if r.role == "assistant":
            replies.setdefault((r.context_json or {}).get("reply_to"), []).append(r)
    return [_entry(r, replies.get(r.id)) for r in rows if r.role == "user"]


def _recent_turns(db: Session, session_id: str) -> list[dict]:
    rows = db.scalars(select(m.ChatMessage).where(m.ChatMessage.session_id == session_id)
                      .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()).limit(6)).all()
    # 직전 질문만 준다(후속 질문의 말이 이어지도록). 직전 답변 문장은 주지 않는다 — 모델이 그대로 베껴 쓴다.
    return [{"q": e["text"]} for e in _pair(list(reversed(rows)))]


def _already_said(db: Session, session_id: str, mode: str) -> list[str]:
    """이 모드로 이미 한 답변(최근 3개). 같은 문장을 되풀이하지 않게 '반복 금지' 목록으로만 쓴다."""
    rows = db.scalars(select(m.ChatMessage).where(m.ChatMessage.session_id == session_id, m.ChatMessage.role == "assistant")
                      .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()).limit(30)).all()
    return [r.content for r in rows if (r.context_json or {}).get("mode") == mode][:3]


@router.get("/chat")
def get_chat(mode: str | None = None, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """이 모드의 대화만 돌려준다(모드마다 대화가 따로다)."""
    session = _mode_session(db, member.id, _body_mode(db, member.id, mode))
    if not session:
        return {"entries": []}
    rows = db.scalars(select(m.ChatMessage).where(m.ChatMessage.session_id == session.id)
                      .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()).limit(CHAT_KEEP * 2)).all()
    return {"entries": _pair(list(reversed(rows)))[-CHAT_KEEP:]}


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    mode: str | None = None  # 화면에 보이는 모드. 있으면 그 말투로 답한다(저장된 설정과 어긋나도 화면 기준)
    roastLevel: int | None = None  # 싸가지 모드 욕설 강도 1~3. 없으면 저장된 설정


def _prepare_turn(db: Session, member_id: str, body: ChatIn) -> dict:
    """질문 해석 → 계산(판정·숫자 확정) → 질문 저장. 답변 생성에 필요한 것을 모아 돌려준다."""
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "EMPTY_TEXT")
    mode = _body_mode(db, member_id, body.mode)
    session = _mode_session(db, member_id, mode) or _new_session(db, member_id, mode)
    recent = _recent_turns(db, session.id)

    u = understand(text)
    # "응 등록해": 방금 얘기한 금액(결제 확인 등)을 기록해 달라는 말이면 그 금액·분류로 기록한다
    if u.intent == "record" and u.amount is None and is_record_command(text):
        recent_user = db.scalars(select(m.ChatMessage).where(m.ChatMessage.session_id == session.id, m.ChatMessage.role == "user")
                                 .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()).limit(6)).all()
        cand = next((x for x in recent_user if (x.context_json or {}).get("amount")), None)
        cctx = (cand.context_json or {}) if cand else {}
        if cand and not cctx.get("recorded") and not cctx.get("income") and cand.intent in ("purchase", "record"):
            cat, hint = find_category_hint(cand.content)
            u = dataclasses.replace(u, amount=cctx["amount"], category=cctx.get("category") or cat, hint=hint, days_ago=0)
    # 금액만 말한 답("3만원"): 바로 앞 질문이 금액 없는 수입·지출 기록이었다면 그 기록의 금액으로 이어 간다
    if u.intent == "purchase" and u.amount is not None and not re.sub(r"[\d,.\s만천원…~]", "", text):
        prev_msg = db.scalar(select(m.ChatMessage).where(m.ChatMessage.session_id == session.id, m.ChatMessage.role == "user")
                             .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()))
        pc = (prev_msg.context_json or {}) if prev_msg else {}
        if prev_msg and prev_msg.intent in ("income", "record") and pc.get("amount") is None                 and not pc.get("income") and not pc.get("recorded"):
            if prev_msg.intent == "income":
                u = dataclasses.replace(u, intent="income", hint=income_source(prev_msg.content),
                                        days_ago=parse_days_ago(prev_msg.content))
            else:
                cat, hint = find_category_hint(prev_msg.content)
                u = dataclasses.replace(u, intent="record", category=cat, hint=hint, days_ago=parse_days_ago(prev_msg.content))
    # 후속 질문: 문장에 카테고리가 없으면 직전 질문의 카테고리를 이어받는다
    category = u.category
    if category is None:
        last = db.scalar(select(m.ChatMessage).where(m.ChatMessage.session_id == session.id, m.ChatMessage.role == "user")
                         .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()))
        category = (last.context_json or {}).get("category", DEFAULT_CATEGORY) if last else DEFAULT_CATEGORY

    if u.intent == "income":
        category = u.category or UNCATEGORIZED
    if u.intent == "record":  # 쓴 돈을 기록할 때는 직전 질문의 분류를 이어받지 않는다(말이 없으면 기타)
        category = u.category or UNCATEGORIZED
    ctx: dict = {"amount": u.amount, "category": category, "nlu": u.source, "mode": mode}
    if u.intent == "purchase" and u.amount is not None:
        ctx["check"] = judge_payment(db, member_id, u.amount, category, record=False)
    if u.intent == "income" and u.amount is not None:
        day = date.today() - timedelta(days=u.days_ago)
        try:
            tx = create_income(db, member_id, day, u.hint or "수입", u.amount)
            when = "오늘" if u.days_ago == 0 else "어제" if u.days_ago == 1 else f"{u.days_ago}일 전"
            ctx["income"] = {"id": tx.id, "amount": u.amount, "source": u.hint or "수입", "date": day.isoformat(), "when": when}
        except HTTPException as e:
            ctx["incomeError"] = str(e.detail)
    if u.intent == "record" and u.amount is not None:
        day = date.today() - timedelta(days=u.days_ago)
        try:
            tx = create_tx(db, member_id, day, f"{u.hint or category} · 대화 입력", category, u.amount)
            when = "오늘" if u.days_ago == 0 else "어제" if u.days_ago == 1 else f"{u.days_ago}일 전"
            ctx["recorded"] = {"id": tx.id, "amount": u.amount, "category": category, "date": day.isoformat(), "when": when}
        except HTTPException as e:
            ctx["recordError"] = str(e.detail)
    if u.intent == "record" and u.amount is None:  # "등록했어?" → 이 대화방에서 방금 기록한 것을 다시 알려 준다
        prev = db.scalars(select(m.ChatMessage).where(m.ChatMessage.session_id == session.id, m.ChatMessage.role == "user")
                          .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()).limit(10)).all()
        last_rec = next((x.context_json["recorded"] for x in prev if (x.context_json or {}).get("recorded")), None)
        if last_rec:
            ctx["recorded"] = last_rec
    if u.intent == "query":
        # 정해 둔 의도에 안 맞는 조회 질문: 읽기 전용 SQL 로 푼다(검사·역할·시간 제한은 ledger_query 참고)
        ctx["query"] = ledger_query.public(ledger_query.run(engine, member_id, text))
    if u.intent == "week":
        ctx["week"] = _week(db, member_id)
    if u.intent == "category":
        ctx["catSpent"] = _cat_spent(db, member_id, u.category or category)
    if u.intent in ("last", "prev2"):
        ctx["history"] = _history(db, member_id, 1 if u.intent == "last" else 2)

    msg = m.ChatMessage(session_id=session.id, role="user", content=text, intent=u.intent, context_json=ctx)
    db.add(msg)
    db.commit()  # 질문은 먼저 저장한다(답변을 만드는 도중 연결이 끊겨도 기록은 남는다)

    settings = db.get(m.LedgerSettings, member_id)
    level = body.roastLevel if body.roastLevel in (1, 2, 3) else (settings.roast_level if settings else 1)
    # 판정·숫자는 위에서 코드가 확정했다. LLM 은 이 사실을 현재 말투로 풀어 쓸 뿐이다.
    facts = _answer_facts(u.intent, text, ctx, build_summary(db, member_id, this_month()))
    said = _already_said(db, session.id, mode)
    return {"session": session, "msg": msg, "mode": mode, "level": level, "recent": recent, "said": said, "facts": facts}


def _save_reply(db: Session, t: dict, text: str) -> m.ChatMessage:
    reply = m.ChatMessage(session_id=t["session"].id, role="assistant", content=text, intent=t["msg"].intent,
                          context_json={"mode": t["mode"], "source": "llm", "reply_to": t["msg"].id, "roastLevel": t["level"]})
    db.add(reply)
    db.commit()
    return reply


@router.post("/chat", status_code=201)
def ask(body: ChatIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """한 번에 답변을 돌려준다(스트리밍을 안 쓰는 호출용)."""
    t = _prepare_turn(db, member.id, body)
    answer = generate_answer(t["facts"], t["mode"], t["level"], t["recent"], t["said"])
    reply = _save_reply(db, t, answer["text"]) if answer else None
    return _entry(t["msg"], [reply] if reply else None)


class NewChatIn(BaseModel):
    mode: str


@router.post("/chat/new", status_code=201)
def new_chat(body: NewChatIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """이 모드의 대화를 새로 시작한다(다른 모드의 대화는 그대로다)."""
    if body.mode not in MODES:
        raise HTTPException(400, "INVALID_MODE")
    _new_session(db, member.id, body.mode)
    return {"entries": []}


def _sse(event: str, data: dict) -> str:
    return "event: " + event + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@router.post("/chat/stream")
def ask_stream(body: ChatIn, member: m.Member = Depends(current_member)):
    """답변을 SSE 로 흘려 준다.  meta(질문 해석 결과) → delta(글자 조각)* → done(저장된 최종 대화 한 건).

    done 에 answer 가 없으면(LLM 실패·검증 탈락) 화면이 템플릿 문장으로 바꿔 보여 준다.
    """
    member_id = member.id
    if not body.text.strip():
        raise HTTPException(400, "EMPTY_TEXT")

    def gen():
        with SessionLocal() as db:  # 응답이 흐르는 동안 쓸 자체 세션(요청 의존성 세션은 먼저 닫힌다)
            try:
                t = _prepare_turn(db, member_id, body)
            except HTTPException as e:
                yield _sse("error", {"code": e.detail})
                return
            yield _sse("meta", _entry(t["msg"]))
            final = None
            if answer_enabled():
                for ev, payload in stream_answer(t["facts"], t["mode"], t["level"], t["recent"], t["said"]):
                    if ev == "delta":
                        yield _sse("delta", {"t": payload})
                    elif ev == "reset":
                        yield _sse("reset", {})
                    elif ev == "final":
                        final = payload
            reply = _save_reply(db, t, final) if final else None
            yield _sse("done", _entry(t["msg"], [reply] if reply else None))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ───────────── 모드 설정 ─────────────


class SettingsIn(BaseModel):
    mode: str | None = None
    roastLevel: int | None = None  # 싸가지 모드 욕설 강도 (1 순한맛 / 2 보통 / 3 매운맛)


@router.get("/settings")
def get_settings(member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    row = db.get(m.LedgerSettings, member.id)
    return {"mode": row.mode if row else "basic", "roastLevel": row.roast_level if row else 1}


@router.put("/settings")
def put_settings(body: SettingsIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    if body.mode is not None and body.mode not in MODES:
        raise HTTPException(400, "INVALID_MODE")
    if body.roastLevel is not None and body.roastLevel not in (1, 2, 3):
        raise HTTPException(400, "INVALID_ROAST_LEVEL")
    row = db.get(m.LedgerSettings, member.id)
    if not row:
        row = m.LedgerSettings(member_id=member.id, mode=body.mode or "basic", roast_level=body.roastLevel or 1)
        db.add(row)
    if body.mode is not None:
        row.mode = body.mode
    if body.roastLevel is not None:
        row.roast_level = body.roastLevel
    db.commit()
    return {"mode": row.mode, "roastLevel": row.roast_level}


# ───────────── 소비 내역 ─────────────
#
# 지출 기록은 "모의 카드 승인"이다. 카드 도메인의 card_transactions 에 승인 행을 넣고
# ledger_tx_category(source='user') 에 사용자가 고른 분류를 남긴다. 카드 설계서는 거래를 만드는
# 카드 API가 없다고 했으므로, 가계부 모듈이 직접 쓰는 이 경로는 데모 용도다(팀 합의 필요).
# 'source=user' 행만 삭제할 수 있다(시드 거래는 삭제 불가).


def _prev_month(month: str) -> str:
    y, mo = int(month[:4]), int(month[5:])
    y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    return f"{y:04d}-{mo:02d}"


def _adjust_card_bill(db: Session, member_id: str, card: m.Card, tx_date: date, delta: int) -> None:
    """신용카드 승인은 미결제 카드대금(planned_outflows)을 늘리고, 삭제하면 줄인다.

    기획안 3절: 카드 승인 시점에는 미결제 카드대금이 늘고 계좌 잔액은 실제 출금 때 줄어든다.
    이번 달 거래만 이번 달 예정 출금에 반영한다.
    """
    if card.type != "credit" or tx_date.strftime("%Y-%m") != this_month():
        return
    today = date.today()
    row = db.scalar(
        select(m.PlannedOutflow)
        .where(m.PlannedOutflow.member_id == member_id, m.PlannedOutflow.type == "card_bill",
               m.PlannedOutflow.ref_id == card.id, m.PlannedOutflow.status == "planned",
               m.PlannedOutflow.due_date >= today)
        .order_by(m.PlannedOutflow.due_date)
    )
    if row:
        row.amount = max(0, row.amount + delta)
    elif delta > 0:
        day = min(card.payment_day or 25, 28)
        due = date(today.year, today.month, day)
        if due < today:  # 이번 달 결제일이 지났으면 다음 달
            due = date(today.year + (today.month == 12), today.month % 12 + 1, day)
        db.add(m.PlannedOutflow(member_id=member_id, due_date=due, amount=delta, type="card_bill",
                                ref_type="card", ref_id=card.id))


@router.get("/transactions")
def transactions(
    month: str = Query(default_factory=this_month),
    member: m.Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    start, end = month_range(month)
    ledger_categorize.ensure_categories(db, member.id)
    cat = func.coalesce(m.LedgerTxCategory.category, UNCATEGORIZED)
    rows = db.execute(
        select(m.CardTransaction, cat, m.LedgerTxCategory.source)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(
            m.LedgerTxCategory,
            m.LedgerTxCategory.card_transaction_id == func.coalesce(m.CardTransaction.original_id, m.CardTransaction.id),
        )
        .where(m.Card.member_id == member.id,
               m.CardTransaction.occurred_at >= start, m.CardTransaction.occurred_at < end)
        .order_by(m.CardTransaction.occurred_at.desc(), m.CardTransaction.id.desc())
    ).all()

    items = [{
        "id": tx.id,
        "date": tx.occurred_at.date().isoformat(),
        "merchant": tx.merchant,
        "category": category,
        "kind": tx.kind,
        # 화면 표시용 부호: 승인은 지출(-), 취소는 환불(+)
        "amount": -tx.amount if tx.kind == "approval" else tx.amount,
        "canDelete": tx.kind == "approval" and source == "user",
        "canEdit": tx.kind == "approval",
        "userMade": source == "user",
    } for tx, category, source in rows]

    now_by_cat = category_spent(db, member.id, start, end)
    prev_start, prev_end = month_range(_prev_month(month))
    prev_spent = sum(category_spent(db, member.id, prev_start, prev_end).values())
    top = max(now_by_cat.items(), key=lambda kv: kv[1], default=(None, 0))
    spent = sum(now_by_cat.values())
    return {
        "month": month,
        "items": items,
        "report": {
            "spent": spent,
            "prevSpent": prev_spent,
            "hasPrev": prev_spent != 0,
            "delta": spent - prev_spent,
            "topCategory": top[0] if top[1] > 0 else None,
            "topAmount": top[1] if top[1] > 0 else 0,
            "income": _income(db, member.id, start, end),
        },
    }


class TxIn(BaseModel):
    date: date
    merchant: str = Field(min_length=1, max_length=30)
    category: str
    amount: int = Field(gt=0, le=100_000_000)


def create_tx(db: Session, member_id: str, day: date, merchant: str, category: str, amount: int) -> m.CardTransaction:
    """카드 지출 한 건을 기록한다(화면 입력과 대화 입력이 같이 쓴다). 실패하면 HTTPException."""
    merchant = merchant.strip()
    if not merchant:
        raise HTTPException(400, "INVALID_MERCHANT")
    if category not in CATEGORIES:
        raise HTTPException(400, "INVALID_CATEGORY")
    if day > date.today():
        raise HTTPException(400, "FUTURE_DATE")  # 미래 날짜는 기록할 수 없다 (시안과 동일)
    # 기록할 카드: 사용 중인 카드 중 신용카드를 우선한다
    card = db.scalar(
        select(m.Card).where(m.Card.member_id == member_id, m.Card.status == "active")
        .order_by(case((m.Card.type == "credit", 0), else_=1), m.Card.issued_at)
    )
    if not card:
        raise HTTPException(409, "NO_ACTIVE_CARD")
    tx = m.CardTransaction(
        card_id=card.id, kind="approval", merchant=merchant, amount=amount, installment_months=0,
        occurred_at=datetime.combine(day, time(12, 0)))
    db.add(tx)
    db.flush()
    db.add(m.LedgerTxCategory(card_transaction_id=tx.id, member_id=member_id, category=category, source="user"))
    _adjust_card_bill(db, member_id, card, day, amount)
    db.commit()
    return tx


@router.post("/transactions", status_code=201)
def add_transaction(body: TxIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    return {"id": create_tx(db, member.id, body.date, body.merchant, body.category, body.amount).id}


@router.delete("/transactions/{tx_id}", status_code=204)
def delete_transaction(tx_id: str, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    row = db.execute(
        select(m.CardTransaction, m.LedgerTxCategory)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .join(m.LedgerTxCategory, m.LedgerTxCategory.card_transaction_id == m.CardTransaction.id)
        .where(m.CardTransaction.id == tx_id, m.Card.member_id == member.id)
    ).first()
    if not row:
        raise HTTPException(404, "NOT_FOUND")
    tx, cat = row
    if cat.source != "user" or tx.kind != "approval":
        raise HTTPException(409, "NOT_DELETABLE")
    if db.scalar(select(m.CardTransaction.id).where(m.CardTransaction.original_id == tx.id)):
        raise HTTPException(409, "HAS_CANCEL")
    card = db.get(m.Card, tx.card_id)
    _adjust_card_bill(db, member.id, card, tx.occurred_at.date(), -tx.amount)
    db.delete(cat)
    db.flush()
    db.delete(tx)
    db.commit()


class TxEdit(BaseModel):
    category: str | None = None
    merchant: str | None = Field(default=None, min_length=1, max_length=30)
    amount: int | None = Field(default=None, gt=0, le=100_000_000)


@router.put("/transactions/{tx_id}")
def edit_transaction(tx_id: str, body: TxEdit, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """분류는 모든 승인 거래에서 바꿀 수 있고, 사용처·금액은 직접 기록한 거래만 바꿀 수 있다."""
    row = db.execute(
        select(m.CardTransaction, m.LedgerTxCategory)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(m.LedgerTxCategory, m.LedgerTxCategory.card_transaction_id == m.CardTransaction.id)
        .where(m.CardTransaction.id == tx_id, m.Card.member_id == member.id)
    ).first()
    if not row:
        raise HTTPException(404, "NOT_FOUND")
    tx, cat = row
    if tx.kind != "approval":
        raise HTTPException(409, "NOT_EDITABLE")
    user_made = cat is not None and cat.source == "user"
    if (body.merchant is not None or body.amount is not None) and not user_made:
        raise HTTPException(409, "ONLY_CATEGORY")
    if body.amount is not None and body.amount != tx.amount:
        if db.scalar(select(m.CardTransaction.id).where(m.CardTransaction.original_id == tx.id)):
            raise HTTPException(409, "HAS_CANCEL")
        card = db.get(m.Card, tx.card_id)
        _adjust_card_bill(db, member.id, card, tx.occurred_at.date(), body.amount - tx.amount)
        tx.amount = body.amount
    if body.merchant is not None and body.merchant.strip():
        tx.merchant = body.merchant.strip()
    if body.category is not None:
        if body.category not in CATEGORIES:
            raise HTTPException(400, "INVALID_CATEGORY")
        if cat:
            cat.category = body.category  # 직접 기록한 거래는 source 그대로, 자동 분류 거래는 분류만 바꾼다
        else:
            db.add(m.LedgerTxCategory(card_transaction_id=tx.id, member_id=member.id, category=body.category, source="auto"))
    db.commit()
    return {"id": tx.id}


@router.get("/transactions/export")
def export_transactions(month: str = Query(default_factory=this_month), member: m.Member = Depends(current_member),
                        db: Session = Depends(get_db)):
    """그 달 카드 내역을 CSV 로 내려준다(엑셀에서 한글이 깨지지 않게 BOM 을 붙인다)."""
    data = transactions(month=month, member=member, db=db)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["날짜", "사용처", "분류", "구분", "금액(원)"])
    for x in reversed(data["items"]):
        w.writerow([x["date"], x["merchant"], x["category"], "취소" if x["kind"] == "cancel" else "승인", x["amount"]])
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ledger-{month}.csv"'})


@router.get("/trend")
def trend(months: int = Query(6, ge=2, le=12), member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """최근 N개월(오래된 순) 월별 지출·수입과 분류별 지출."""
    ledger_categorize.ensure_categories(db, member.id)
    out = []
    for back in range(months - 1, -1, -1):
        month = _prev_n_month(back)
        start, end = month_range(month)
        by_cat = category_spent(db, member.id, start, end)
        out.append({"month": month, "spent": sum(by_cat.values()), "income": _income(db, member.id, start, end),
                    "byCategory": by_cat})
    return {"months": out}


# ───────────── 고정지출 후보 ─────────────

RECURRING_SKIP = "대화 입력"  # 대화로 직접 기록한 건 반복 결제로 보지 않는다


def _next_day(last: date) -> date:
    """같은 날짜의 다음 도래일(이번 달 그 날이 안 지났으면 이번 달)."""
    today = date.today()
    day = min(last.day, 28)
    due = date(today.year, today.month, day)
    if due < today:
        due = date(today.year + (today.month == 12), today.month % 12 + 1, day)
    return due


@router.get("/recurring")
def recurring(member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """최근 6개월에 서로 다른 2개월 이상 비슷한 금액(±10%)으로 반복된 결제를 고정지출 후보로 보여 준다."""
    since = date.today().replace(day=1) - timedelta(days=150)
    cat = func.coalesce(m.LedgerTxCategory.category, UNCATEGORIZED)
    rows = db.execute(
        select(m.CardTransaction.merchant, m.CardTransaction.amount, m.CardTransaction.occurred_at, cat)
        .join(m.Card, m.Card.id == m.CardTransaction.card_id)
        .outerjoin(m.LedgerTxCategory, m.LedgerTxCategory.card_transaction_id == m.CardTransaction.id)
        .where(m.Card.member_id == member.id, m.CardTransaction.kind == "approval",
               m.CardTransaction.occurred_at >= datetime.combine(since, time.min))
        .order_by(m.CardTransaction.occurred_at)
    ).all()
    groups: dict[str, list] = {}
    for merchant, amount, when, category in rows:
        if RECURRING_SKIP not in merchant:
            groups.setdefault(merchant, []).append((amount, when.date(), category))
    registered = {p.ref_id for p in db.scalars(select(m.PlannedOutflow).where(
        m.PlannedOutflow.member_id == member.id, m.PlannedOutflow.type == "fixed",
        m.PlannedOutflow.status == "planned"))}
    items = []
    for merchant, tx in groups.items():
        med = statistics.median(a for a, _, _ in tx)
        same = [t for t in tx if abs(t[0] - med) <= med * 0.1]
        months = {d.strftime("%Y-%m") for _, d, _ in same}
        if len(months) < 2:
            continue
        last = same[-1]
        items.append({"merchant": merchant, "category": last[2], "amount": last[0], "months": len(months),
                      "lastDate": last[1].isoformat(), "nextDate": _next_day(last[1]).isoformat(),
                      "registered": merchant[:40] in registered})
    items.sort(key=lambda x: -x["amount"])
    return {"items": items}


class RecurringIn(BaseModel):
    merchant: str = Field(min_length=1, max_length=40)
    amount: int = Field(gt=0, le=100_000_000)
    dueDate: date


@router.post("/recurring/register", status_code=201)
def register_recurring(body: RecurringIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """고정지출을 예정 출금(type=fixed)에 올린다. 같은 사용처는 한 번만."""
    if body.dueDate < date.today():
        raise HTTPException(400, "PAST_DATE")
    key = body.merchant[:40]
    if db.scalar(select(m.PlannedOutflow.id).where(
            m.PlannedOutflow.member_id == member.id, m.PlannedOutflow.type == "fixed",
            m.PlannedOutflow.ref_id == key, m.PlannedOutflow.status == "planned")):
        raise HTTPException(409, "ALREADY_REGISTERED")
    row = m.PlannedOutflow(member_id=member.id, due_date=body.dueDate, amount=body.amount, type="fixed",
                           ref_type="recurring", ref_id=key)
    db.add(row)
    db.commit()
    return {"id": row.id}


# ───────────── 저축 목표 ─────────────


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    target: int = Field(gt=0, le=10_000_000_000)


@router.put("/goal")
def put_goal(body: GoalIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    month = this_month()
    g = db.scalar(select(m.LedgerGoal).where(m.LedgerGoal.member_id == member.id, m.LedgerGoal.month == month))
    if g:
        g.name, g.target_amount = body.name.strip(), body.target
    else:
        db.add(m.LedgerGoal(member_id=member.id, month=month, name=body.name.strip(), target_amount=body.target))
    db.commit()
    return _goal(db, member.id, month, _saved(db, member.id, month_range(month)[0])["heldAmount"])


@router.delete("/goal", status_code=204)
def delete_goal(member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    g = db.scalar(select(m.LedgerGoal).where(m.LedgerGoal.member_id == member.id, m.LedgerGoal.month == this_month()))
    if g:
        db.delete(g)
        db.commit()


# ───────────── 영수증 사진 → 지출 입력값 ─────────────

RECEIPT_SYSTEM = """영수증 사진에서 카드 지출 한 건의 값을 읽어 JSON 으로만 답한다. 계산하거나 추측하지 않는다.
merchant: 상호(가게 이름). 읽을 수 없으면 null.
date: 결제 날짜 YYYY-MM-DD. 읽을 수 없으면 null.
amount: 최종 결제 금액(합계)을 원 단위 정수로. 읽을 수 없으면 null.
category: 배달, 외식, 장보기, 쇼핑, 교통, 생활, 기타 중 가장 알맞은 하나."""
RECEIPT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "merchant": {"type": "STRING", "nullable": True},
        "date": {"type": "STRING", "nullable": True},
        "amount": {"type": "INTEGER", "nullable": True},
        "category": {"type": "STRING", "enum": CATEGORIES},
    },
    "required": ["merchant", "date", "amount", "category"],
}
RECEIPT_MIME = ("image/jpeg", "image/png", "image/webp")


class ReceiptIn(BaseModel):
    image: str = Field(max_length=7_000_000)  # base64 (약 5MB 사진)
    mime: str


@router.post("/receipt")
def read_receipt(body: ReceiptIn, member: m.Member = Depends(current_member)):
    """영수증 사진을 읽어 입력 칸에 채울 값을 돌려준다. 저장은 하지 않는다(사용자가 확인한 뒤 기록)."""
    if body.mime not in RECEIPT_MIME:
        raise HTTPException(400, "INVALID_IMAGE")
    try:
        base64.b64decode(body.image, validate=True)
    except Exception:
        raise HTTPException(400, "INVALID_IMAGE") from None
    try:
        raw = generate_json_image(RECEIPT_SYSTEM, body.image, body.mime, RECEIPT_SCHEMA)
    except LlmUnavailable:
        raise HTTPException(503, "OCR_UNAVAILABLE") from None
    amount = raw.get("amount")
    amount = amount if isinstance(amount, int) and not isinstance(amount, bool) and 0 < amount <= 100_000_000 else None
    day = None
    try:
        day = date.fromisoformat(str(raw.get("date")))
    except ValueError:
        pass
    if day is None or day > date.today():
        day = date.today()
    category = raw.get("category") if raw.get("category") in CATEGORIES else UNCATEGORIZED
    merchant = (raw.get("merchant") or "").strip()[:30] or None
    return {"merchant": merchant, "date": day.isoformat(), "amount": amount, "category": category}


# ───────────── 수입(들어온 돈) ─────────────

INCOME_MEMO = "가계부 입력"  # 가계부에서 직접 기록한 입금 표시. 이 표시가 있는 것만 지울 수 있다.
INCOME_KINDS = ("deposit", "transfer_in")


def create_income(db: Session, member_id: str, day: date, source: str, amount: int) -> m.AccountTransaction:
    """대표계좌에 입금을 기록하고 잔액을 늘린다(화면 입력과 대화 입력이 같이 쓴다)."""
    source = source.strip()[:30]
    if not source:
        raise HTTPException(400, "INVALID_SOURCE")
    if day > date.today():
        raise HTTPException(400, "FUTURE_DATE")
    acc = db.scalar(select(m.Account).where(m.Account.member_id == member_id, m.Account.is_primary.is_(True),
                                            m.Account.status == "active"))
    if not acc:
        raise HTTPException(409, "NO_PRIMARY_ACCOUNT")
    acc.balance += amount
    tx = m.AccountTransaction(account_id=acc.id, kind="deposit", amount=amount, balance_after=acc.balance,
                              counterparty=source, memo=INCOME_MEMO, occurred_at=datetime.combine(day, time(9, 0)))
    db.add(tx)
    db.commit()
    return tx


class IncomeIn(BaseModel):
    date: date
    source: str = Field(min_length=1, max_length=30)
    amount: int = Field(gt=0, le=10_000_000_000)


@router.post("/income", status_code=201)
def add_income(body: IncomeIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    return {"id": create_income(db, member.id, body.date, body.source, body.amount).id}


@router.get("/income")
def list_income(month: str = Query(default_factory=this_month), member: m.Member = Depends(current_member),
                db: Session = Depends(get_db)):
    start, end = month_range(month)
    rows = db.scalars(
        select(m.AccountTransaction).join(m.Account, m.Account.id == m.AccountTransaction.account_id)
        .where(m.Account.member_id == member.id, m.AccountTransaction.kind.in_(INCOME_KINDS),
               m.AccountTransaction.occurred_at >= datetime.combine(start, time.min),
               m.AccountTransaction.occurred_at < datetime.combine(end, time.min))
        .order_by(m.AccountTransaction.occurred_at.desc(), m.AccountTransaction.id.desc())).all()
    return {"month": month, "items": [{
        "id": r.id, "date": r.occurred_at.date().isoformat(), "source": r.counterparty or r.memo or "입금",
        "amount": r.amount, "canDelete": r.memo == INCOME_MEMO} for r in rows]}


@router.delete("/income/{tx_id}", status_code=204)
def delete_income(tx_id: str, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """가계부에서 기록한 수입만 지운다. 그만큼 잔액을 되돌리고, 잔액이 모자라면 못 지운다."""
    row = db.execute(
        select(m.AccountTransaction, m.Account).join(m.Account, m.Account.id == m.AccountTransaction.account_id)
        .where(m.AccountTransaction.id == tx_id, m.Account.member_id == member.id)).first()
    if not row:
        raise HTTPException(404, "NOT_FOUND")
    tx, acc = row
    if tx.memo != INCOME_MEMO or tx.kind not in INCOME_KINDS:
        raise HTTPException(409, "NOT_DELETABLE")
    if acc.balance < tx.amount:
        raise HTTPException(409, "BALANCE_TOO_LOW")
    acc.balance -= tx.amount
    db.delete(tx)
    db.commit()


@router.get("/account-outflows")
def account_outflows(month: str = Query(default_factory=this_month), member: m.Member = Depends(current_member),
                     db: Session = Depends(get_db)):
    """내 계좌에서 나간 돈(출금·이체). 카드대금·대출상환은 카드 지출·예정 출금과 겹쳐서 뺀다. 예산 계산에는 넣지 않는다."""
    start, end = month_range(month)
    rows = db.execute(
        select(m.AccountTransaction, m.Account.account_masked)
        .join(m.Account, m.Account.id == m.AccountTransaction.account_id)
        .where(m.Account.member_id == member.id, m.AccountTransaction.kind.in_(("withdraw", "transfer_out")),
               m.AccountTransaction.occurred_at >= datetime.combine(start, time.min),
               m.AccountTransaction.occurred_at < datetime.combine(end, time.min))
        .order_by(m.AccountTransaction.occurred_at.desc(), m.AccountTransaction.id.desc())).all()
    items = [{"id": t.id, "date": t.occurred_at.date().isoformat(), "kind": t.kind,
              "to": t.counterparty or t.memo or "출금", "amount": t.amount, "account": masked} for t, masked in rows]
    return {"month": month, "total": sum(i["amount"] for i in items), "items": items}


# ───────────── 예산 · 예정 출금 설정 ─────────────


class BudgetIn(BaseModel):
    total: int = Field(gt=0, le=10_000_000_000)
    categories: dict[str, int] = {}  # 예: {"배달": 90000}
    clear: list[str] = []  # 예산을 없앨 분류


@router.put("/budget")
def put_budget(body: BudgetIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """이번 달 월 예산과 카테고리 예산을 저장한다(없으면 만든다)."""
    for name, amount in body.categories.items():
        if name not in CATEGORIES:
            raise HTTPException(400, "INVALID_CATEGORY")
        if amount <= 0:
            raise HTTPException(400, "INVALID_AMOUNT")
    month = this_month()
    budget = db.scalar(select(m.Budget).where(m.Budget.member_id == member.id, m.Budget.month == month))
    if budget:
        budget.total_amount = body.total
    else:
        budget = m.Budget(member_id=member.id, month=month, total_amount=body.total, emergency_floor=0)
        db.add(budget)
        db.flush()
    for name, amount in body.categories.items():
        row = db.get(m.CategoryBudget, (budget.id, name))
        if row:
            row.amount = amount
        else:
            db.add(m.CategoryBudget(budget_id=budget.id, category=name, amount=amount))
    for name in body.clear:
        if name in CATEGORIES:
            row = db.get(m.CategoryBudget, (budget.id, name))
            if row:
                db.delete(row)
    db.commit()
    return build_summary(db, member.id, month)


class PlannedIn(BaseModel):
    amount: int = Field(ge=0, le=10_000_000_000)


@router.put("/planned-outflows/{po_id}")
def put_planned(po_id: str, body: PlannedIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    """예정 출금(카드대금 등) 금액을 고친다. 계좌 잔액은 계좌 도메인 소유라 여기서 바꾸지 않는다."""
    row = db.get(m.PlannedOutflow, po_id)
    if not row or row.member_id != member.id:
        raise HTTPException(404, "NOT_FOUND")
    row.amount = body.amount
    db.commit()
    return build_summary(db, member.id, this_month())
