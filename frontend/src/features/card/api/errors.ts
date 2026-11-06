export type ApiErrorCode =
  | 'VALIDATION_FAILED'
  | 'INVALID_CURSOR'
  | 'IDEMPOTENCY_KEY_REQUIRED'
  | 'LOGIN_REQUIRED'
  | 'SESSION_EXPIRED'
  | 'PIN_SETUP_REQUIRED'
  | 'PIN_VERIFICATION_REQUIRED'
  | 'CARD_NOT_FOUND'
  | 'ACCOUNT_NOT_FOUND'
  | 'TRANSACTION_NOT_FOUND'
  | 'CARD_STATE_INVALID'
  | 'CARD_COUNT_LIMIT_EXCEEDED'
  | 'CARD_TERMINATE_BLOCKED_UNPAID'
  | 'APPLICANT_NOT_ELIGIBLE'
  | 'IDEMPOTENCY_KEY_REUSED'
  | 'INTERNAL_ERROR'
  | 'ACCOUNT_SERVICE_UNAVAILABLE'
  | 'MEMBER_SERVICE_UNAVAILABLE'
  | 'NETWORK_ERROR'
  | 'TIMEOUT'

export class ApiError extends Error {
  status: number
  code: ApiErrorCode
  details?: Record<string, unknown>

  constructor(status: number, code: ApiErrorCode, message: string, details?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export type FieldError = { field: string; reason: string }

export const toApiError = (e: unknown): ApiError =>
  e instanceof ApiError ? e : new ApiError(0, 'NETWORK_ERROR', '네트워크 오류')
