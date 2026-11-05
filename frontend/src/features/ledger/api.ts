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
