"""가계부 답변 문장 생성 (규칙 + LLM 혼합, 스트리밍).

역할 분담
  - 규칙(서버 코드): 가능/보류 판정과 모든 숫자를 확정한다 → `facts`
  - LLM(Gemini)   : 확정된 사실을 현재 모드(말투)로 풀어 쓴다. 글자가 만들어지는 대로 흘려 보낸다(스트리밍)
  - 실시간 검증   : 흘려 보내기 전에 매 조각마다 확인한다
                    · 첫 줄의 판정(VERDICT)이 사실과 같은가
                    · 사실에 없는 숫자가 없는가
                    · 금칙어(모드·강도별), 내부 키워드, 길이
                    어긋나면 즉시 끊는다. 아직 아무것도 안 보냈으면 한 번 다시 시도하고, 이미 보냈으면 실패로 알린다
                    (실패면 화면이 템플릿 문장으로 바꿔 보여 준다).

LLM 은 숫자를 계산하거나 판정을 바꾸지 못한다. 바꾸면 검증에서 걸러진다.
"""
import json
import logging
import os
import re
from typing import Iterator

from .gemini import LlmUnavailable, stream_text

log = logging.getLogger("ledger.answer")

# ───────────── 말투 ─────────────

TONE = {
    "basic": (
        "기본 모드. 반드시 차분한 존댓말(~입니다/~해요)로만 말하고 반말은 쓰지 않는다. 계산 결과를 정확하게 알려준다. "
        "예: '20,000원 결제 시 배달 예산을 11,000원 초과합니다. 결제를 보류했습니다.' 욕설·비속어 금지."
    ),
    "kind": (
        "착한 모드. 반드시 다정한 반말(~해, ~야, ~자, ~줄게)로만 말하고 존댓말(~요, ~습니다, ~세요)은 절대 쓰지 않는다. 격려하고, 보류일 때도 부드럽게 금액을 줄이는 등 대안을 제안한다. "
        "예: '20,000원은 지금 배달 예산을 넘어서 잠깐 멈춰 줄게. 금액을 줄여 볼까?' 욕설·비속어 금지."
    ),
    "numbers": (
        "숫자만 모드. 감정 표현 없이 '항목명 값 / 항목명 값 / 상태 ...' 형태로 한 줄만 적는다. 모든 숫자 앞에 항목명을 붙인다. "
        "문장형 설명 금지. 상태는 한글(가능/보류)로 쓰고 영어 키워드는 쓰지 않는다. 잡담에는 '입력 해석 불가' 정도로만 답한다. "
        "예: '요청 20,000원 / 사유 배달 예산 초과 / 상태 보류'"
    ),
}

ROAST_BASE = (
    "싸가지 모드. 사용자가 무슨 말을 하든(질문, 인사, 잡담, 시비, 의미 없는 글자까지) 끝까지 싸가지 없고 거칠게 "
    "반말로 대꾸한다. 존댓말·공손함·사과·칭찬 금지. 돈 얘기가 나오면 사실은 정확히 말해 준다. "
    "욕은 사용자의 소비 습관과 행동을 향해서만 한다(존재·외모·가족·출신을 깎아내리지 마라). "
    "인종·성별·지역·장애·가족 비하, 성적 표현, 협박, 자해 언급은 절대 쓰지 않는다. "
    "예: '20,000원? 배달 예산 넘는다. 정신 차려. 이 결제는 보류야.'"
)
ROAST_LEVEL = {
    1: "강도 1(순한맛): 욕설·비속어는 한 마디도 쓰지 않는다('개소리', '지랄', '미친', '젠장' 같은 말도 금지). 비꼬고 얕잡아 보는 반말로만 쏘아붙인다.",
    2: "강도 2(보통): 모든 문장에 가벼운 욕설을 반드시 하나 이상 섞는다. 예: 젠장, 지랄, 미친, 빌어먹을, 염병, 개소리. 씨발·시발·존나 같은 센 욕은 쓰지 않는다.",
    3: "강도 3(매운맛): 모든 문장에 찰진 욕설을 반드시 하나 이상, 되도록 두세 개 섞는다. 예: 씨발, 시발, 지랄, 염병, 존나, 개소리, 썅, 미친. 순하게 쓰지 마라. 단, 위의 금지 사항은 그대로 지킨다.",
}

_SYSTEM = """너는 은행 가계부 앱의 '답변 작성기'다. 아래 '사실'만 근거로 사용자의 말에 답하는 문장을 쓴다.

규칙:
1. 판정(verdict)과 모든 숫자는 서버가 이미 계산했다. 바꾸거나 다시 계산하지 말고, 사실에 없는 숫자를 쓰지 마라.
2. 사실의 verdict 가 held 면 결제를 말리며 '보류'를 알리고, allowed 면 가능하다고 알린다. 판정이 없는 질문은 info.
3. 금액은 반드시 '20,000원'처럼 천 단위 쉼표 + '원'으로 쓴다. '2만 원' 같은 축약은 쓰지 마라.
4. 1~2문장, 120자 이내. (숫자만 모드는 한 줄.)
5. 투자·대출·상품 추천이나 사실에 없는 조언 금지.
6. needAmount 가 true 면 얼마를 쓸 건지 금액을 되물어라.
7. 항목 이름과 값을 정확히 짝지어 써라. '월 예산'(전체)과 '분류 예산'(배달 예산 등), '전체 지출'과 '분류 지출'을 혼동하지 마라.
   사실에 '설정 없음'이라고 된 예산이나 사실에 없는 항목은 언급하지 마라.
8. 사실에 '질문'이 '잡담 또는 의도 불명확'이면 숫자를 쓰지 말고, 말투를 지킨 채 한두 문장으로 대꾸한 뒤
   잔액·예산·지난달 지출·결제 가능 여부를 물어보라고 가계부 쪽으로 이끌어라.
9. recent 는 직전 대화다. 말이 자연스럽게 이어지도록만 참고하고, 거기 나온 숫자는 쓰지 마라.

말투: {tone}

출력 형식(반드시 지켜라): 첫 줄에 `VERDICT: held` 또는 `VERDICT: allowed` 또는 `VERDICT: info` 만 쓰고, 줄을 바꾼 뒤 답변 문장만 쓴다.
설명·마크다운·따옴표·머리말 금지."""

VERDICT_RE = re.compile(r"^\s*VERDICT\s*:\s*(held|allowed|info)\s*$", re.I)

# ───────────── 금칙어 ─────────────
# 어떤 모드·강도에서도 금지: 비하·혐오·가족 욕설·성적 표현·협박·자해
HARD_BANNED = [
    "병신", "븅신", "장애인", "장애", "애미", "애비", "느금", "니미", "니애미", "패드립", "창녀", "걸레", "섹스", "강간",
    "한남", "김치녀", "된장녀", "틀딱", "찐따", "메갈", "일베", "죽어", "뒤져", "자살", "좆", "보지", "씹창", "흑인", "짱깨",
]
# 싸가지 모드의 욕설 강도에 따라 허용: 강도 1 이하와 다른 모드에서는 모두 금지
SOFT_MILD = ["젠장", "지랄", "염병", "미친", "빌어먹", "꺼져", "닥쳐", "멍청", "한심", "개소리"]
SOFT_STRONG = ["시발", "씨발", "ㅅㅂ", "ㅆㅂ", "존나", "졸라", "썅", "씹", "엿먹"]

LEAKED = ["info", "held", "allowed", "verdict", "null", "none", "true", "false"]  # 내부 키워드가 문장에 새면 안 된다
MAX_LEN = 200


def banned_words(mode: str, roast_level: int) -> list[str]:
    words = list(HARD_BANNED)
    if mode == "roast" and roast_level >= 3:
        return words
    if mode == "roast" and roast_level == 2:
        return words + SOFT_STRONG  # 보통: 가벼운 욕설만
    return words + SOFT_MILD + SOFT_STRONG  # 순한맛·다른 모드: 욕설 금지


def enabled() -> bool:
    flag = os.getenv("LEDGER_ANSWER") or os.getenv("LEDGER_NLU") or "rules"
    return flag.strip().lower() == "llm"


# ───────────── 검증 ─────────────


def _ints(obj) -> set[int]:
    """facts 안의 모든 정수(절댓값). LLM 이 써도 되는 숫자의 집합이다."""
    out: set[int] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int):
        out.add(abs(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _ints(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _ints(v)
    return out


_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(만|%)?")


def _numbers_ok(text: str, facts: dict) -> bool:
    allowed = _ints(facts) | {0}
    pct = {v for k, v in facts.items() if k.endswith("사용률") and isinstance(v, int)}
    for raw, unit in _NUM.findall(text):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            return False
        if unit == "%":
            if round(value) not in pct:
                return False
            continue
        if unit == "만":
            value *= 10000
        if value != int(value):
            return False
        value = int(value)
        # 100 미만의 맨숫자('3일', '2번')는 날짜·횟수 표현일 수 있어 허용, 그 외는 사실에 있어야 한다
        if value < 100 and not unit and f"{raw}원" not in text:
            continue
        if value not in allowed:
            return False
    return True


def check_text(text: str, facts: dict, mode: str, roast_level: int) -> str | None:
    """문장(또는 지금까지 만든 앞부분)이 통과하면 None, 막히면 사유."""
    if len(text) > MAX_LEN:
        return "length"
    if any(w in text for w in banned_words(mode, roast_level)):
        return "banned word"
    low = text.lower()
    if any(re.search(rf"(?<![a-z]){w}(?![a-z])", low) for w in LEAKED):
        return "leaked keyword"
    if not _numbers_ok(text, facts):
        return "number not in facts"
    return None


def validate(text: str, verdict: str, facts: dict, mode: str = "basic", roast_level: int = 1) -> str | None:
    """완성된 답변 전체 검증. 통과하면 None, 막히면 사유."""
    text = (text or "").strip()
    if not text:
        return "length"
    if verdict != facts["verdict"]:
        return "verdict mismatch"
    return check_text(text, facts, mode, roast_level)


def _safe_len(buf: str) -> int:
    """아직 끝나지 않았을 수 있는 꼬리(숫자·금칙어가 잘린 조각)를 빼고, 내보내도 되는 길이."""
    idx = max(0, len(buf) - 5)
    while idx > 0 and buf[idx - 1] in "0123456789,.":
        idx -= 1
    return idx


# ───────────── 생성 ─────────────


class _Reject(Exception):
    pass


def _system(mode: str, roast_level: int, retry_reason: str | None = None) -> str:
    tone = f"{ROAST_BASE} {ROAST_LEVEL.get(roast_level, ROAST_LEVEL[2])}" if mode == "roast" else TONE[mode]
    text = _SYSTEM.replace("{tone}", tone)
    if retry_reason:  # 직전 시도가 검증에서 거절됐다. 무엇이 잘못됐는지 알려 준다.
        text += "\n\n[주의] 직전 답변이 검증에서 거절됐다(사유: " + retry_reason + "). 말투·강도·금지 사항·사실의 숫자를 정확히 지켜서 다시 써라."
    return text


def stream_answer(facts: dict, mode: str, roast_level: int, recent: list[dict]) -> Iterator[tuple[str, str]]:
    """('delta', 새 글자) 를 계속 내보내고, 성공하면 ('final', 전체 문장), 쓸 수 없으면 ('fail', 사유) 로 끝난다."""
    if not enabled() or (mode != "roast" and mode not in TONE):
        yield ("fail", "disabled")
        return
    payload = json.dumps({"facts": facts, "recent": recent[-3:]}, ensure_ascii=False)
    temperature = 0.95 if mode == "roast" else 0.7

    why_last: str | None = None
    for attempt in (1, 2):
        system = _system(mode, roast_level, why_last)
        emitted, buf, verdict = 0, "", None
        try:
            for chunk in stream_text(system, payload, timeout_default=8.0, temperature=temperature if attempt == 1 else 0.3):
                buf += chunk
                if verdict is None:  # 첫 줄(판정)이 올 때까지는 아무것도 보내지 않는다
                    if "\n" not in buf:
                        continue
                    head, _, rest = buf.partition("\n")
                    m = VERDICT_RE.match(head)
                    if not m or m.group(1).lower() != facts["verdict"]:
                        raise _Reject("verdict mismatch")
                    verdict, buf = m.group(1).lower(), rest.lstrip("\n")
                safe = _safe_len(buf)
                why = check_text(buf[:safe], facts, mode, roast_level)
                if why:
                    raise _Reject(why)
                if safe > emitted:
                    yield ("delta", buf[emitted:safe])
                    emitted = safe
            if verdict is None:
                raise _Reject("no verdict")
            text = buf.rstrip()
            why = validate(text, verdict, facts, mode, roast_level)
            if why:
                raise _Reject(why)
            if len(text) > emitted:
                yield ("delta", text[emitted:])
            yield ("final", text)
            return
        except _Reject as e:
            log.warning("LLM 답변 검증 실패(%s) %d번째, 이미 보낸 글자 %d", e, attempt, emitted)
            why_last = str(e)
            if emitted > 0 or attempt == 2:  # 이미 화면에 나갔으면 다시 시도하지 않는다
                yield ("fail", str(e))
                return
        except LlmUnavailable as e:
            log.warning("LLM 답변 실패, 템플릿으로 대체: %s", e)
            yield ("fail", str(e))
            return
    yield ("fail", "exhausted")


def generate_answer(facts: dict, mode: str, roast_level: int, recent: list[dict]) -> dict | None:
    """스트림을 끝까지 모아서 {text, mode, source} 로 돌려준다(스트리밍을 안 쓰는 호출용). 쓸 수 없으면 None."""
    final = None
    for ev, payload in stream_answer(facts, mode, roast_level, recent):
        if ev == "final":
            final = payload
    return {"text": final, "mode": mode, "source": "llm"} if final else None
