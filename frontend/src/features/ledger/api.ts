// 가계부 API 타입 (backend/app/ledger.py 응답과 맞춘다)
export type Mode = 'roast' | 'basic' | 'kind' | 'numbers'
export type Level = 'safe' | 'caution' | 'danger'
export type Reason = 'MONTH_BUDGET' | 'BALANCE' | 'CATEGORY_BUDGET'

export type Summary = {
  month: string
  budget: { total: number; spent: number; remaining: number; ratio: number; emergencyFloor: number; set: boolean }
  risk: { level: Level; ratio: number; hotCategories: string[] }
  categories: {
    category: string
    budget: number | null
    spent: number
    remaining: number | null
    ratio: number | null
    over: boolean
  }[]
  account: { id: string; bankName: string; masked: string } | null
  balance: {
    current: number
    plannedOutflow: number
    expected: number
    planned: { id: string; dueDate: string; amount: number; type: string }[]
  }
}

export type Check = {
  result: 'allowed' | 'held'
  reasons: Reason[]
  limits: { MONTH_BUDGET: number; BALANCE: number; CATEGORY_BUDGET: number | null }
  overAmount: number
  after: { budgetRemaining: number; expectedBalance: number; categoryRemaining: number | null }
  category: string
  amount: number
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export const fetchSummary = (month?: string): Promise<Summary> =>
  fetch(`/api/ledger/summary${month ? `?month=${month}` : ''}`).then((r) => json<Summary>(r))

/** record=false 면 판정만 하고 결제 시도 기록(payment_attempts)은 남기지 않는다. */
export const checkPayment = (amount: number, category: string, record: boolean): Promise<Check> =>
  fetch('/api/ledger/payment-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ amount, category, record }),
  }).then((r) => json<Check>(r))

export const fetchMode = (): Promise<Mode> =>
  fetch('/api/ledger/settings').then((r) => json<{ mode: Mode }>(r)).then((d) => d.mode)

export const saveMode = (mode: Mode): Promise<unknown> =>
  fetch('/api/ledger/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  }).then((r) => json<unknown>(r))

// ───────── 소비 내역 ─────────
export type Tx = {
  id: string
  date: string
  merchant: string
  category: string
  kind: 'approval' | 'cancel'
  /** 화면 표시용 부호 포함 금액: 지출은 음수, 환불은 양수 */
  amount: number
  canDelete: boolean
}

export type TxList = {
  month: string
  items: Tx[]
  report: {
    spent: number
    prevSpent: number
    hasPrev: boolean
    delta: number
    topCategory: string | null
    topAmount: number
  }
}

export const fetchTransactions = (month: string): Promise<TxList> =>
  fetch(`/api/ledger/transactions?month=${month}`).then((r) => json<TxList>(r))

export class ApiError extends Error {
  constructor(public code: string) {
    super(code)
  }
}

async function send(url: string, method: string, body?: unknown): Promise<Response> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new ApiError(typeof d.detail === 'string' ? d.detail : `HTTP_${res.status}`)
  }
  return res
}

export const addTransaction = (b: { date: string; merchant: string; category: string; amount: number }) =>
  send('/api/ledger/transactions', 'POST', b)

export const deleteTransaction = (id: string) => send(`/api/ledger/transactions/${id}`, 'DELETE')

export const saveBudget = (total: number, categories: Record<string, number>) =>
  send('/api/ledger/budget', 'PUT', { total, categories })

export const savePlanned = (id: string, amount: number) => send(`/api/ledger/planned-outflows/${id}`, 'PUT', { amount })
