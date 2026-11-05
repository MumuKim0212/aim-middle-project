"""Gemini REST 호출 (표준 라이브러리만 사용).

- API 키는 환경변수 GEMINI_API_KEY 에서만 읽고, URL 이 아닌 헤더(x-goog-api-key)로 보낸다.
- 키·요청 본문·응답 본문은 로그와 예외 메시지에 남기지 않는다.
- 어떤 실패든 LlmUnavailable 하나로 바꿔서 던진다. 호출한 쪽이 규칙/템플릿으로 되돌린다.
"""
import json
import os
import urllib.error
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LlmUnavailable(Exception):
    """LLM 을 쓸 수 없거나 응답이 쓸 만하지 않을 때."""


def _settings(timeout_default: float) -> tuple[str, str, float]:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise LlmUnavailable("no key")
    model = (os.getenv("GEMINI_MODEL") or "gemini-3.6-flash").strip()
    try:
        timeout = float(os.getenv("GEMINI_TIMEOUT_SEC") or timeout_default)
    except ValueError:
        timeout = timeout_default
    return key, model, timeout


def generate_json(system: str, user_text: str, schema: dict, *, timeout_default: float = 4.0,
                  temperature: float = 0.0) -> dict:
    """system 지시와 사용자 입력을 보내고, schema 모양의 JSON 객체를 받는다."""
    key, model, timeout = _settings(timeout_default)
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": schema,
            # 짧은 해석·문장 생성이라 '생각' 토큰을 쓰지 않는다(지연·비용 절약). 미지원 모델이면 무시된다.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        GEMINI_URL.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    except urllib.error.HTTPError as e:
        raise LlmUnavailable(f"HTTP {e.code}") from None
    except Exception as e:  # 시간 초과, 연결 실패, JSON 이상 등
        raise LlmUnavailable(type(e).__name__) from None


STREAM_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"


def stream_text(system: str, user_text: str, *, timeout_default: float = 6.0, temperature: float = 0.7):
    """응답 텍스트를 조각(chunk) 단위로 흘려 준다(SSE). 어떤 실패든 LlmUnavailable 로 던진다."""
    key, model, timeout = _settings(timeout_default)
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": temperature, "thinkingConfig": {"thinkingBudget": 0}},
    }).encode("utf-8")
    req = urllib.request.Request(
        STREAM_URL.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            for raw in res:  # 한 줄씩 읽는다
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    parts = json.loads(payload)["candidates"][0]["content"]["parts"]
                except (KeyError, IndexError, ValueError):
                    continue
                chunk = "".join(p.get("text", "") for p in parts)
                if chunk:
                    yield chunk
    except urllib.error.HTTPError as e:
        raise LlmUnavailable(f"HTTP {e.code}") from None
    except LlmUnavailable:
        raise
    except GeneratorExit:
        raise
    except Exception as e:
        raise LlmUnavailable(type(e).__name__) from None


def generate_json_image(system: str, image_b64: str, mime: str, schema: dict, *, timeout_default: float = 20.0) -> dict:
    """이미지 한 장(base64)과 지시를 보내고 schema 모양의 JSON 을 받는다. 어떤 실패든 LlmUnavailable."""
    key, model, timeout = _settings(timeout_default)
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": mime, "data": image_b64}}]}],
        "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json", "responseSchema": schema,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }).encode("utf-8")
    req = urllib.request.Request(
        GEMINI_URL.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    except urllib.error.HTTPError as e:
        raise LlmUnavailable(f"HTTP {e.code}") from None
    except Exception as e:
        raise LlmUnavailable(type(e).__name__) from None
