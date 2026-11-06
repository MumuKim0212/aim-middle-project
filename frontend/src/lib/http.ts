// API 호출 공통 래퍼(기획서 6.1): 쿠키 세션을 보내고, 401/403 이면 로그인·간편비밀번호 설정 화면으로 보낸다.
export type FieldError = { field: string; reason?: string; message?: string }
// 오류 응답 모양: { code, message, details? } (공통.md 5장). 추가 값은 details 안에 있다.
export type ApiErrorBody = {
  code?: string
  message?: string
  details?: { fields?: FieldError[]; until?: string; remainingAttempts?: number }
  detail?: string
}

/** VALIDATION_FAILED 의 첫 필드 오류(없으면 undefined). */
export function firstFieldError(body: ApiErrorBody): FieldError | undefined {
  return body.details?.fields?.[0]
}

export class ApiFail extends Error {
  constructor(public status: number, public body: ApiErrorBody) {
    super(body.message || body.code || `HTTP ${status}`)
  }
  get code() {
    return this.body.code
  }
}

/** 로그인 뒤 돌아갈 곳은 우리 사이트 안의 경로만 허용한다(외부 주소는 무시). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('://')) return null
  if (next.startsWith('/login') || next.startsWith('/signup')) return null
  return next
}

function onAuthFailure(status: number, body: ApiErrorBody) {
  const path = location.pathname
  if (path.startsWith('/login') || path.startsWith('/signup')) return
  if (status === 401 && (body.code === 'LOGIN_REQUIRED' || body.code === 'SESSION_EXPIRED')) {
    const next = encodeURIComponent(path + location.search)
    location.assign(`/login?next=${next}${body.code === 'SESSION_EXPIRED' ? '&expired=1' : ''}`)
  } else if (status === 403 && body.code === 'PIN_SETUP_REQUIRED' && !path.startsWith('/auth/pin/setup')) {
    location.assign('/auth/pin/setup')
  }
}

export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(input, { credentials: 'include', ...init })
  if (res.status === 401 || res.status === 403) {
    const body = (await res.clone().json().catch(() => ({}))) as ApiErrorBody
    onAuthFailure(res.status, body)
  }
  return res
}

/** JSON 으로 보내고 받는다. 실패하면 ApiFail(상태·code·message)을 던진다. */
export async function callJson<T = unknown>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await apiFetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiFail(res.status, data as ApiErrorBody)
  return data as T
}
