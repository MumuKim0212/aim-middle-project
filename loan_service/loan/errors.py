"""[역할] 대출 서비스 예외 계층: 화면에 보여 줄 안전한 메시지와 내부 원인을 분리한다."""
from __future__ import annotations


class LoanError(Exception):
    """모든 대출 예외의 부모. user_message만 화면에 노출한다(내부 정보 노출 방지)."""

    user_message = "요청을 처리하지 못했습니다."

    def __init__(self, user_message: str | None = None, *, detail: str | None = None):
        self.user_message = user_message or self.user_message
        self.detail = detail          # 로그용(개인정보 없이)
        super().__init__(self.user_message)


class ValidationError(LoanError):
    user_message = "입력값을 확인해 주세요."


class ConsentMissing(LoanError):
    user_message = "필요한 동의가 없어 조회할 수 없습니다."


class InvalidTransition(LoanError):
    user_message = "지금 단계에서는 할 수 없는 요청입니다."


class LimitExceeded(LoanError):
    user_message = "한도금액을 초과하였습니다."


class RateLimited(LoanError):
    user_message = "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."


class DuplicateRequest(LoanError):
    user_message = "이미 처리된 요청입니다."


class GuardrailViolation(LoanError):
    user_message = "안전 검증을 통과하지 못해 기본 안내로 대신합니다."


class SagaFailed(LoanError):
    user_message = "처리 중 문제가 생겨 거래를 원래대로 되돌렸습니다."


class NotFound(LoanError):
    user_message = "대상을 찾을 수 없습니다."
