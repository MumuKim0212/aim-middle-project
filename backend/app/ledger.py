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
import json
import re
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import models as m
from .db import SessionLocal, get_db
from .deps import current_member
from .ledger_answer import enabled as answer_enabled, generate_answer, stream_answer
from .ledger_nlu import understand

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


def build_summary(db: Session, member_id: str, month: str) -> dict:
    start, end = month_range(month)
    spent_by_cat = category_spent(db, member_id, start, end)
    spent = sum(spent_by_cat.values())

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


def _entry(msg: m.ChatMessage, reply: m.ChatMessage | None = None) -> dict:
    ctx = msg.context_json or {}
    rctx = (reply.context_json or {}) if reply else {}
    return {
        "id": msg.id, "text": msg.content, "intent": msg.intent,
        "amount": ctx.get("amount"), "category": ctx.get("category", DEFAULT_CATEGORY),
        "check": ctx.get("check"), "history": ctx.get("history"),
        # LLM 이 쓴 답변(검증 통과분). 없으면 화면이 템플릿 문장을 쓴다.
        "answer": {"text": reply.content, "mode": rctx.get("mode"), "source": rctx.get("source", "llm")} if reply else None,
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
        d = next((c for c in s["categories"] if c["category"] == "배달" and c["budget"] is not None), None)
        if d:
            facts.update({"배달 예산 남은 금액": d["remaining"], "배달 예산 사용률": d["ratio"]})
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


def _latest_session(db: Session, member_id: str) -> m.ChatSession | None:
    return db.scalar(select(m.ChatSession).where(m.ChatSession.member_id == member_id)
                     .order_by(m.ChatSession.created_at.desc(), m.ChatSession.id.desc()))


def _pair(rows: list[m.ChatMessage]) -> list[dict]:
    """시간순 메시지에서 사용자 질문마다 그 답변(assistant)을 짝지어 돌려준다."""
    replies = {(r.context_json or {}).get("reply_to"): r for r in rows if r.role == "assistant"}
    return [_entry(r, replies.get(r.id)) for r in rows if r.role == "user"]


def _recent_turns(db: Session, session_id: str) -> list[dict]:
    rows = db.scalars(select(m.ChatMessage).where(m.ChatMessage.session_id == session_id)
                      .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()).limit(6)).all()
    return [{"q": e["text"], **({"a": e["answer"]["text"]} if e["answer"] else {})} for e in _pair(list(reversed(rows)))]


@router.get("/chat")
def get_chat(member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    session = _latest_session(db, member.id)
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
    session = _latest_session(db, member_id)
    if not session:
        session = m.ChatSession(member_id=member_id)
        db.add(session)
        db.flush()
    recent = _recent_turns(db, session.id)

    u = understand(text)
    # 후속 질문: 문장에 카테고리가 없으면 직전 질문의 카테고리를 이어받는다
    category = u.category
    if category is None:
        last = db.scalar(select(m.ChatMessage).where(m.ChatMessage.session_id == session.id, m.ChatMessage.role == "user")
                         .order_by(m.ChatMessage.created_at.desc(), m.ChatMessage.id.desc()))
        category = (last.context_json or {}).get("category", DEFAULT_CATEGORY) if last else DEFAULT_CATEGORY

    ctx: dict = {"amount": u.amount, "category": category, "nlu": u.source}
    if u.intent == "purchase" and u.amount is not None:
        ctx["check"] = judge_payment(db, member_id, u.amount, category, record=False)
    if u.intent in ("last", "prev2"):
        ctx["history"] = _history(db, member_id, 1 if u.intent == "last" else 2)

    msg = m.ChatMessage(session_id=session.id, role="user", content=text, intent=u.intent, context_json=ctx)
    db.add(msg)
    db.commit()  # 질문은 먼저 저장한다(답변을 만드는 도중 연결이 끊겨도 기록은 남는다)

    settings = db.get(m.LedgerSettings, member_id)
    mode = body.mode if body.mode in MODES else (settings.mode if settings else "basic")
    level = body.roastLevel if body.roastLevel in (1, 2, 3) else (settings.roast_level if settings else 1)
    # 판정·숫자는 위에서 코드가 확정했다. LLM 은 이 사실을 현재 말투로 풀어 쓸 뿐이다.
    facts = _answer_facts(u.intent, text, ctx, build_summary(db, member_id, this_month()))
    return {"session": session, "msg": msg, "mode": mode, "level": level, "recent": recent, "facts": facts}


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
    answer = generate_answer(t["facts"], t["mode"], t["level"], t["recent"])
    return _entry(t["msg"], _save_reply(db, t, answer["text"]) if answer else None)


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
                for ev, payload in stream_answer(t["facts"], t["mode"], t["level"], t["recent"]):
                    if ev == "delta":
                        yield _sse("delta", {"t": payload})
                    elif ev == "final":
                        final = payload
            reply = _save_reply(db, t, final) if final else None
            yield _sse("done", _entry(t["msg"], reply))

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
        },
    }


class TxIn(BaseModel):
    date: date
    merchant: str = Field(min_length=1, max_length=30)
    category: str
    amount: int = Field(gt=0, le=100_000_000)


@router.post("/transactions", status_code=201)
def add_transaction(body: TxIn, member: m.Member = Depends(current_member), db: Session = Depends(get_db)):
    merchant = body.merchant.strip()
    if not merchant:
        raise HTTPException(400, "INVALID_MERCHANT")
    if body.category not in CATEGORIES:
        raise HTTPException(400, "INVALID_CATEGORY")
    if body.date > date.today():
        raise HTTPException(400, "FUTURE_DATE")  # 미래 날짜는 기록할 수 없다 (시안과 동일)
    # 기록할 카드: 사용 중인 카드 중 신용카드를 우선한다
    card = db.scalar(
        select(m.Card).where(m.Card.member_id == member.id, m.Card.status == "active")
        .order_by(case((m.Card.type == "credit", 0), else_=1), m.Card.issued_at)
    )
    if not card:
        raise HTTPException(409, "NO_ACTIVE_CARD")
    tx = m.CardTransaction(
        card_id=card.id, kind="approval", merchant=merchant, amount=body.amount, installment_months=0,
        occurred_at=datetime.combine(body.date, time(12, 0)))
    db.add(tx)
    db.flush()
    db.add(m.LedgerTxCategory(card_transaction_id=tx.id, member_id=member.id, category=body.category, source="user"))
    _adjust_card_bill(db, member.id, card, body.date, body.amount)
    db.commit()
    return {"id": tx.id}


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


# ───────────── 예산 · 예정 출금 설정 ─────────────


class BudgetIn(BaseModel):
    total: int = Field(gt=0, le=10_000_000_000)
    categories: dict[str, int] = {}  # 예: {"배달": 90000}


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
