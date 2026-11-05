import { ApiError, type ApiErrorCode } from './errors'

const BASE = '/api/v1'
const TIMEOUT_MS = 10_000

type Query = Record<string, string | number | boolean | undefined | null>

type Options = {
  query?: Query
  body?: unknown
  headers?: Record<string, string>
}

const withQuery = (path: string, query?: Query) => {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  const qs = params.toString()
  return qs ? `${BASE}${path}?${qs}` : `${BASE}${path}`
}

export async function request<T>(method: 'GET' | 'POST', path: string, opts: Options = {}): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, TIMEOUT_MS)

  try {
    let res: Response
    try {
      res = await fetch(withQuery(path, opts.query), {
        method,
        headers: {
          Accept: 'application/json',
          ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...opts.headers,
        },
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      })
    } catch {
      throw timedOut
        ? new ApiError(0, 'TIMEOUT', '요청 시간이 초과되었습니다.')
        : new ApiError(0, 'NETWORK_ERROR', '네트워크 오류')
    }

    const text = await res.text().catch(() => '')
    let json: unknown = null
    try {
      json = text ? JSON.parse(text) : null
    } catch {
      // non-JSON body: handled below
    }

    if (!res.ok) {
      const e = (json ?? {}) as { code?: string; message?: string; details?: Record<string, unknown> }
      throw new ApiError(
        res.status,
        (e.code ?? 'INTERNAL_ERROR') as ApiErrorCode,
        e.message ?? '요청을 처리하지 못했습니다.',
        e.details,
      )
    }
    return json as T
  } finally {
    clearTimeout(timer)
  }
}
