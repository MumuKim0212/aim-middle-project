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
  /** 예시 금액도 DB 에서 계산해서 내려온다(질문 칩·입력칸 예시·시뮬레이션 버튼) */
  examples: { category: string; typical: number; large: number }
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

export type Settings = { mode: Mode; roastLevel: number }

export const fetchSettings = (): Promise<Settings> => fetch('/api/ledger/settings').then((r) => json<Settings>(r))

/** 바꿀 것만 보낸다. roastLevel 은 싸가지 모드의 욕설 강도(1 순한맛 / 2 보통 / 3 매운맛). */
export const saveSettings = (patch: Partial<Settings>): Promise<unknown> =>
  fetch('/api/ledger/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
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

// ───────── 물어보기(대화) ─────────
export type Intent = 'purchase' | 'balance' | 'budget' | 'last' | 'prev2' | 'chat'
export type History = { month: string; spent: number; delta: number; topName: string; topAmount: number }
/** 서버가 해석·계산한 질문 한 건. 답변 문장은 모드(말투)에 따라 화면에서 만든다. */
export type Entry = {
  id?: string
  text: string
  intent: Intent
  amount: number | null
  category: string
  check?: Check | null
  history?: History | null
  /** LLM 이 쓴 답변(서버 검증 통과분). 없으면 화면이 템플릿 문장을 쓴다. */
  answer?: { text: string; mode: Mode | null; source: string } | null
}

export const fetchChat = (): Promise<Entry[]> =>
  fetch('/api/ledger/chat').then((r) => json<{ entries: Entry[] }>(r)).then((d) => d.entries)

export type StreamHandlers = {
  onMeta?: (entry: Entry) => void
  /** 답변 글자 조각이 도착할 때마다 */
  onDelta: (text: string) => void
  /** 저장까지 끝난 최종 대화 한 건. answer 가 없으면 화면이 템플릿 문장을 쓴다. */
  onDone: (entry: Entry) => void
}

/**
 * 질문을 보내고 답변을 SSE 로 받는다(meta → delta* → done).
 * mode·roastLevel 은 화면에 보이는 값이다. 서버가 그 말투와 욕설 강도로 답한다.
 */
export async function streamChat(text: string, mode: Mode, roastLevel: number, h: StreamHandlers): Promise<void> {
  const res = await fetch('/api/ledger/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, mode, roastLevel }),
  })
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let finished = false

  const dispatch = (block: string) => {
    let event = ''
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!event || !data) return
    const payload = JSON.parse(data)
    if (event === 'meta') h.onMeta?.(payload as Entry)
    else if (event === 'delta') h.onDelta((payload as { t: string }).t)
    else if (event === 'done') {
      finished = true
      h.onDone(payload as Entry)
    } else if (event === 'error') throw new Error((payload as { code?: string }).code ?? 'STREAM_ERROR')
  }

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      dispatch(block)
    }
  }
  if (!finished) throw new Error('STREAM_ENDED')
}
