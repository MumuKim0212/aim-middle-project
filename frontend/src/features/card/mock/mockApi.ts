// 데모용 목업 API. 함수 시그니처와 오류는 docs/dev/card/frontend-spec.md 3.3절과 같다.
// shortcut: 실제 서버 전환 스위치(VITE_USE_MOCK)와 비로그인 흉내는 아직 없다. 서버가 생기면 cardApi.ts에서 바꾼다.
import { ApiError, type ApiErrorCode, type FieldError } from '../api/errors'
import type {
  ApplyEligibility, BillingItem, BillingPayment, CardAction, CardApplicationRequest,
  CardApplicationResult, CardDetail, CardLimit, CardListResponse, CardProduct, CardStatus,
  CardStatusResult, CardSummary, CreditLimit, IncomeRange, PaymentAccount, TerminateRequest,
  TerminateResult, TerminationCheck, TransactionDetail, TransactionItem, TransactionListParams,
  TransactionListResponse, UpcomingBilling,
} from '../api/types'
import { advance, nowIso, nowMs, resetClock, setNow, today } from '../lib/clock'
import {
  billed, cycleLines, cycleTotals, firstDueDate, nextPaymentDate, usageRate, usedAmount, type Tx,
} from '../lib/cycles'
import { addMonths, dateOf, daysBetween, isValidDate, kstDate, pad, parseDate, yearsBetween } from '../lib/dates'
import { isSimplePin } from '../lib/pin'
import {
  MEMBER_BIRTH_DATE, accountFixtures, cardFixtures, txFixtures, type AccountRow, type CardRow,
} from './fixtures'

type State = {
  cards: CardRow[]
  txs: Tx[]
  accounts: AccountRow[]
  pins: Map<string, { fail: number; lockedUntil: number }>
  idem: Map<string, { fingerprint: string; response: CardApplicationResult }>
  seq: number
}

const fresh = (): State => ({
  cards: structuredClone(cardFixtures),
  txs: txFixtures(),
  accounts: structuredClone(accountFixtures),
  pins: new Map(),
  idem: new Map(),
  seq: 0,
})

let st = fresh()
const delay = () => new Promise((resolve) => setTimeout(resolve, 150))
const fail = (status: number, code: ApiErrorCode, message: string, details?: Record<string, unknown>) =>
  new ApiError(status, code, message, details)
const validation = (fields: FieldError[]) =>
  fail(400, 'VALIDATION_FAILED', '입력값을 확인해 주세요.', { fields })

// ---------- 공통 ----------
const MAX_CARDS = 3
const PIN_RE = /^[0-9]{4}$/
const ACTIONS: Record<CardStatus, CardAction[]> = {
  active: ['view_transactions', 'view_limit', 'suspend', 'report_lost', 'terminate'],
  suspended: ['view_transactions', 'view_limit', 'resume', 'report_lost', 'terminate'],
  lost: ['view_transactions', 'view_limit', 'terminate'],
  terminated: ['view_transactions'],
}
const STATUS_ORDER: Record<CardStatus, number> = { active: 0, suspended: 1, lost: 2, terminated: 3 }

const findCard = (id: string) => {
  const card = st.cards.find((c) => c.id === id)
  if (!card) throw fail(404, 'CARD_NOT_FOUND', '카드를 찾을 수 없습니다.')
  return card
}
const findAccount = (id: string) => st.accounts.find((a) => a.id === id)
const accountView = (id: string): PaymentAccount => {
  const a = findAccount(id)!
  return { accountId: a.id, bankName: a.bankName, accountMasked: a.masked }
}
const cardTxs = (card: CardRow) => st.txs.filter((t) => t.cardId === card.id)
const totalsOf = (card: CardRow) => cycleTotals(cycleLines(cardTxs(card), card.paymentDay!))
const maskedNumber = (card: CardRow) => `****-****-****-${card.last4}`

const creditView = (card: CardRow): CreditLimit => {
  const used = usedAmount(totalsOf(card), today())
  const total = card.creditLimit!
  return { total, used, remaining: Math.max(0, total - used), usageRate: usageRate(used, total) }
}

const verifyPin = (accountId: string, pin: string) => {
  const account = findAccount(accountId)
  if (!account) throw fail(404, 'ACCOUNT_NOT_FOUND', '계좌를 찾을 수 없습니다.')
  const s = st.pins.get(accountId) ?? { fail: 0, lockedUntil: 0 }
  st.pins.set(accountId, s)
  const now = nowMs()
  const locked = (sec: number) =>
    fail(429, 'ACCOUNT_PIN_LOCKED', '계좌 암호 입력이 잠겼습니다.', { retryAfterSeconds: sec })
  if (now < s.lockedUntil) throw locked(Math.ceil((s.lockedUntil - now) / 1000))
  if (pin === account.pin) {
    s.fail = 0
    return
  }
  s.fail += 1
  if (s.fail >= 5) {
    s.fail = 0
    s.lockedUntil = now + 300_000
    throw locked(300)
  }
  throw fail(403, 'ACCOUNT_PIN_MISMATCH', '계좌 암호가 올바르지 않습니다.', { remainingAttempts: 5 - s.fail })
}

const pinFieldErrors = (pin: unknown): FieldError[] =>
  pin === undefined || pin === '' ? [{ field: 'accountPin', reason: 'REQUIRED' }]
    : typeof pin !== 'string' || !PIN_RE.test(pin) ? [{ field: 'accountPin', reason: 'INVALID_FORMAT' }]
    : []

const statusResult = (c: CardRow): CardStatusResult => ({
  id: c.id, status: c.status, suspendedAt: c.suspendedAt, lostAt: c.lostAt, lostReason: c.lostReason,
})

// ---------- 01 목록·상세 ----------
const toSummary = (c: CardRow): CardSummary => ({
  id: c.id, name: c.name, type: c.type, numberMasked: maskedNumber(c), status: c.status,
  issuedAt: c.issuedAt, terminatedAt: c.terminatedAt,
})

export async function listCards(opts: { includeTerminated?: boolean } = {}): Promise<CardListResponse> {
  await delay()
  const live = st.cards
    .filter((c) => c.status !== 'terminated')
    .sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.issuedAt.localeCompare(a.issuedAt))
  const gone = st.cards
    .filter((c) => c.status === 'terminated')
    .sort((a, b) => (b.terminatedAt ?? '').localeCompare(a.terminatedAt ?? ''))
  return {
    items: [...live, ...(opts.includeTerminated ? gone : [])].map(toSummary),
    terminatedCount: gone.length,
  }
}

const toDetail = (c: CardRow): CardDetail => ({
  id: c.id, name: c.name, type: c.type, numberMasked: maskedNumber(c), expiry: c.expiry,
  status: c.status, issuedAt: c.issuedAt, paymentAccount: accountView(c.accountId),
  paymentDay: c.paymentDay, limit: c.type === 'credit' ? creditView(c) : null, debitLimit: c.debitLimit,
  suspendedAt: c.suspendedAt, lostAt: c.lostAt, lostReason: c.lostReason, terminatedAt: c.terminatedAt,
  availableActions: ACTIONS[c.status],
})

export async function getCard(cardId: string): Promise<CardDetail> {
  await delay()
  return toDetail(findCard(cardId))
}

// ---------- 02 이용내역 ----------
const toItem = (t: Tx): TransactionItem => {
  const c = findCard(t.cardId)
  return {
    id: t.id, cardId: c.id, cardName: c.name, cardType: c.type, cardNumberLast4: c.last4,
    occurredAt: t.occurredAt, merchant: t.merchant, amount: t.amount, kind: t.kind,
    originalId: t.originalId, installmentMonths: t.installmentMonths,
  }
}

export async function listTransactions(p: TransactionListParams): Promise<TransactionListResponse> {
  await delay()
  const fields: FieldError[] = []
  const T = today()
  for (const key of ['from', 'to'] as const) {
    if (!p[key]) fields.push({ field: key, reason: 'REQUIRED' })
    else if (!isValidDate(p[key])) fields.push({ field: key, reason: 'INVALID_FORMAT' })
  }
  if (isValidDate(p.from) && isValidDate(p.to)) {
    if (p.from > p.to) fields.push({ field: 'from', reason: 'FROM_AFTER_TO' })
    if (p.to > T) fields.push({ field: 'to', reason: 'TO_IN_FUTURE' })
    if (p.from < addMonths(p.to, -12)) fields.push({ field: 'from', reason: 'PERIOD_TOO_LONG' })
  }
  const kind = p.kind ?? 'all'
  if (!['all', 'approval', 'cancel'].includes(kind)) fields.push({ field: 'kind', reason: 'INVALID_ENUM' })
  const q = (p.merchant ?? '').trim().toLowerCase()
  if ([...q].length > 50) fields.push({ field: 'merchant', reason: 'TOO_LONG' })
  const limit = p.limit ?? 20
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) fields.push({ field: 'limit', reason: 'OUT_OF_RANGE' })
  if (fields.length) throw validation(fields)
  if (p.cardId) findCard(p.cardId)

  const filterKey = JSON.stringify([p.cardId ?? '', p.from, p.to, kind, q])
  let offset = 0
  if (p.cursor) {
    try {
      const parsed = JSON.parse(decodeURIComponent(atob(p.cursor))) as { o: number; f: string }
      if (parsed.f !== filterKey) throw new Error('filter')
      offset = parsed.o
    } catch {
      throw fail(400, 'INVALID_CURSOR', '커서가 올바르지 않습니다.')
    }
  }

  const list = st.txs
    .filter((t) => {
      const d = kstDate(t.ts)
      return (!p.cardId || t.cardId === p.cardId) && d >= p.from && d <= p.to &&
        (kind === 'all' || t.kind === kind) && (!q || t.merchant.toLowerCase().includes(q))
    })
    .sort((a, b) => b.ts - a.ts || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0))
  const approvalTotal = list.filter((t) => t.kind === 'approval').reduce((s, t) => s + t.amount, 0)
  const cancelTotal = list.filter((t) => t.kind === 'cancel').reduce((s, t) => s + t.amount, 0)
  const next = offset + limit
  return {
    summary: { approvalTotal, cancelTotal, netTotal: approvalTotal - cancelTotal, count: list.length },
    items: list.slice(offset, next).map(toItem),
    nextCursor: next < list.length ? btoa(encodeURIComponent(JSON.stringify({ o: next, f: filterKey }))) : null,
  }
}

export async function getTransaction(id: string): Promise<TransactionDetail> {
  await delay()
  const t = st.txs.find((x) => x.id === id)
  if (!t) throw fail(404, 'TRANSACTION_NOT_FOUND', '거래를 찾을 수 없습니다.')
  const o = t.originalId ? st.txs.find((x) => x.id === t.originalId) : undefined
  return {
    ...toItem(t),
    original: o ? { id: o.id, occurredAt: o.occurredAt, merchant: o.merchant, amount: o.amount } : null,
  }
}

// ---------- 03 청구 ----------
export async function getUpcomingBilling(): Promise<UpcomingBilling> {
  await delay()
  const T = today()
  const credit = st.cards.filter((c) => c.type === 'credit' && c.status !== 'terminated')
  const groups = new Map<string, BillingPayment>()
  for (const c of credit) {
    const lines = cycleLines(cardTxs(c), c.paymentDay!)
    const P = nextPaymentDate(T, c.paymentDay!)
    const amount = billed(cycleTotals(lines), P)
    if (amount === 0) continue
    const [y, m] = parseDate(P)
    const items: BillingItem[] = lines
      .filter((l) => l.cycle === P)
      .sort((a, b) => b.tx.ts - a.tx.ts)
      .map((l) => ({
        kind: l.kind, occurredAt: l.tx.occurredAt, merchant: l.tx.merchant, amount: l.amount,
        installment: l.installment,
      }))
    const key = `${P}|${c.accountId}`
    const group = groups.get(key) ?? {
      paymentDate: P, isCurrentMonth: P.slice(0, 7) === T.slice(0, 7), paymentAccount: accountView(c.accountId),
      amount: 0, balance: findAccount(c.accountId)!.balance, balanceStatus: 'ok' as const, shortfall: 0, cards: [],
    }
    group.amount += amount
    group.cards.push({
      cardId: c.id, cardName: c.name, status: c.status as 'active' | 'suspended' | 'lost',
      cardNumberLast4: c.last4, amount, usagePeriod: { from: dateOf(y, m - 1, 1), to: dateOf(y, m, 0) }, items,
    })
    groups.set(key, group)
  }
  const payments = [...groups.values()].sort(
    (a, b) => a.paymentDate.localeCompare(b.paymentDate) ||
      a.paymentAccount.accountId.localeCompare(b.paymentAccount.accountId),
  )
  for (const g of payments) {
    const balance = g.balance ?? 0
    g.balanceStatus = balance >= g.amount ? 'ok' : 'insufficient'
    g.shortfall = Math.max(0, g.amount - balance)
  }
  const next = payments[0]?.paymentDate ?? null
  return {
    asOf: T,
    hasCreditCard: credit.length > 0,
    thisMonthTotal: payments.filter((g) => g.isCurrentMonth).reduce((s, g) => s + g.amount, 0),
    nextPaymentDate: next,
    daysUntilPayment: next ? daysBetween(T, next) : null,
    payments,
  }
}

// ---------- 04 분실·정지·재개 ----------
async function changeStatus(
  cardId: string, pin: unknown, allowed: CardStatus[], extra: FieldError[], apply: (c: CardRow) => void,
): Promise<CardStatusResult> {
  await delay()
  const fields = [...extra, ...pinFieldErrors(pin)]
  if (fields.length) throw validation(fields)
  const card = findCard(cardId)
  if (!allowed.includes(card.status)) {
    throw fail(409, 'CARD_STATE_INVALID', '현재 카드 상태에서는 처리할 수 없습니다.', {
      currentStatus: card.status, allowedStatuses: allowed,
    })
  }
  verifyPin(card.accountId, pin as string)
  apply(card)
  return statusResult(card)
}

export const suspendCard = (cardId: string, accountPin: string) =>
  changeStatus(cardId, accountPin, ['active'], [], (c) => {
    c.status = 'suspended'
    c.suspendedAt = nowIso()
  })

export const resumeCard = (cardId: string, accountPin: string) =>
  changeStatus(cardId, accountPin, ['suspended'], [], (c) => {
    c.status = 'active'
    c.suspendedAt = null
  })

export const reportLost = (cardId: string, body: { reason: 'lost' | 'stolen'; accountPin: string }) =>
  changeStatus(
    cardId, body.accountPin, ['active', 'suspended'],
    body.reason === undefined ? [{ field: 'reason', reason: 'REQUIRED' }]
      : body.reason !== 'lost' && body.reason !== 'stolen' ? [{ field: 'reason', reason: 'INVALID_ENUM' }] : [],
    (c) => {
      c.status = 'lost'
      c.suspendedAt = null
      c.lostAt = nowIso()
      c.lostReason = body.reason
    },
  )

// ---------- 05 한도 ----------
export async function getCardLimit(cardId: string): Promise<CardLimit> {
  await delay()
  const c = findCard(cardId)
  if (c.status === 'terminated') {
    throw fail(409, 'CARD_STATE_INVALID', '해지된 카드입니다.', {
      currentStatus: c.status, allowedStatuses: ['active', 'suspended', 'lost'],
    })
  }
  return {
    cardId: c.id, type: c.type, status: c.status,
    credit: c.type === 'credit' ? creditView(c) : null,
    debit: c.type === 'debit' ? c.debitLimit : null,
  }
}

// ---------- 06 신청 ----------
const PRODUCTS: CardProduct[] = [
  { id: 'prod_debit_01', type: 'debit', name: 'AIM 체크카드', description: '결제 계좌에서 바로 출금되는 체크카드' },
  { id: 'prod_credit_01', type: 'credit', name: 'AIM 신용카드', description: '결제일에 한꺼번에 결제하는 신용카드' },
]
const INCOME_LIMIT: Record<IncomeRange, number | null> = {
  none: null, lt_10m: null, '10m_20m': 1_000_000, '20m_40m': 3_000_000, '40m_70m': 5_000_000, gte_70m: 10_000_000,
}

const countOf = (type: 'credit' | 'debit') =>
  st.cards.filter((c) => c.type === type && c.status !== 'lost' && c.status !== 'terminated').length

export async function listCardProducts(): Promise<{ items: CardProduct[] }> {
  await delay()
  return { items: PRODUCTS }
}

export async function listPaymentAccounts(): Promise<{ items: PaymentAccount[] }> {
  await delay()
  return { items: st.accounts.map((a) => accountView(a.id)) }
}

export async function getApplyEligibility(): Promise<ApplyEligibility> {
  await delay()
  const underAge = yearsBetween(MEMBER_BIRTH_DATE, today()) < 19
  const one = (type: 'credit' | 'debit') => {
    const currentCount = countOf(type)
    const reason = type === 'credit' && underAge ? 'AGE_UNDER_19' as const
      : currentCount >= MAX_CARDS ? 'COUNT_EXCEEDED' as const : null
    return { available: reason === null, reason, currentCount, maxCount: MAX_CARDS }
  }
  return { types: { credit: one('credit'), debit: one('debit') } }
}

const validateApply = (b: CardApplicationRequest, key: string | undefined): FieldError[] => {
  const f: FieldError[] = []
  const add = (field: string, reason: string) => f.push({ field, reason })
  const credit = b.type === 'credit'
  if (!key) add('Idempotency-Key', 'REQUIRED')
  else if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(key)) {
    add('Idempotency-Key', 'INVALID_FORMAT')
  }
  if (!b.type) add('type', 'REQUIRED')
  else if (b.type !== 'credit' && b.type !== 'debit') add('type', 'INVALID_ENUM')
  if (!b.productId) add('productId', 'REQUIRED')
  else {
    const p = PRODUCTS.find((x) => x.id === b.productId)
    if (!p) add('productId', 'INVALID_ENUM')
    else if (p.type !== b.type) add('productId', 'PRODUCT_TYPE_MISMATCH')
  }
  if (!b.paymentAccountId) add('paymentAccountId', 'REQUIRED')
  if (credit) {
    if (b.paymentDay !== undefined) {
      if (!Number.isInteger(b.paymentDay)) add('paymentDay', 'INVALID_FORMAT')
      else if (b.paymentDay < 1 || b.paymentDay > 28) add('paymentDay', 'OUT_OF_RANGE')
    }
    if (!b.incomeRange) add('incomeRange', 'REQUIRED')
    else if (!(b.incomeRange in INCOME_LIMIT)) add('incomeRange', 'INVALID_ENUM')
    if (!b.agreements?.creditInquiry) add('agreements.creditInquiry', b.agreements?.creditInquiry === false ? 'MUST_BE_TRUE' : 'REQUIRED')
  } else if (b.type === 'debit') {
    if (b.paymentDay !== undefined) add('paymentDay', 'NOT_ALLOWED')
    if (b.incomeRange !== undefined) add('incomeRange', 'NOT_ALLOWED')
    if (b.agreements?.creditInquiry !== undefined) add('agreements.creditInquiry', 'NOT_ALLOWED')
  }
  if (!b.cardPin) add('cardPin', 'REQUIRED')
  else if (!PIN_RE.test(b.cardPin)) add('cardPin', 'INVALID_FORMAT')
  else if (isSimplePin(b.cardPin)) add('cardPin', 'PIN_TOO_SIMPLE')
  const recipient = (b.recipient ?? '').trim()
  if (!recipient) add('recipient', 'REQUIRED')
  else if ([...recipient].length > 20) add('recipient', 'TOO_LONG')
  if (!b.phone) add('phone', 'REQUIRED')
  else if (!/^010-[0-9]{4}-[0-9]{4}$/.test(b.phone)) add('phone', 'INVALID_FORMAT')
  const line1 = (b.address?.line1 ?? '').trim()
  if (!line1) add('address.line1', 'REQUIRED')
  else if ([...line1].length > 100) add('address.line1', 'TOO_LONG')
  if ([...(b.address?.line2 ?? '')].length > 100) add('address.line2', 'TOO_LONG')
  for (const k of ['cardTerms', 'privacy'] as const) {
    if (b.agreements?.[k] === undefined) add(`agreements.${k}`, 'REQUIRED')
    else if (b.agreements[k] !== true) add(`agreements.${k}`, 'MUST_BE_TRUE')
  }
  f.push(...pinFieldErrors(b.accountPin))
  return f
}

export async function applyCard(body: CardApplicationRequest, idempotencyKey?: string): Promise<CardApplicationResult> {
  await delay()
  const fields = validateApply(body, idempotencyKey)
  if (fields.some((x) => x.field === 'Idempotency-Key' && x.reason === 'REQUIRED')) {
    throw fail(400, 'IDEMPOTENCY_KEY_REQUIRED', 'Idempotency-Key 헤더가 필요합니다.')
  }
  if (fields.length) throw validation(fields)

  // 멱등성: 비밀번호 필드는 지문에서 뺀다. 저장하는 응답은 201뿐이다.
  const { accountPin, cardPin, ...rest } = body
  void accountPin
  void cardPin
  const fingerprint = JSON.stringify({ ...rest, paymentDay: body.type === 'credit' ? (body.paymentDay ?? 25) : undefined })
  const saved = st.idem.get(idempotencyKey!)
  if (saved) {
    if (saved.fingerprint !== fingerprint) throw fail(422, 'IDEMPOTENCY_KEY_REUSED', '같은 키로 다른 내용을 보낼 수 없습니다.')
    return saved.response
  }

  const account = findAccount(body.paymentAccountId)
  if (!account) throw fail(404, 'ACCOUNT_NOT_FOUND', '계좌를 찾을 수 없습니다.')
  if (body.type === 'credit' && yearsBetween(MEMBER_BIRTH_DATE, today()) < 19) {
    throw fail(422, 'APPLICANT_NOT_ELIGIBLE', '만 19세 이상부터 신청할 수 있습니다.', { reason: 'AGE_UNDER_19' })
  }
  const current = countOf(body.type)
  if (current >= MAX_CARDS) {
    throw fail(409, 'CARD_COUNT_LIMIT_EXCEEDED', '보유 한도를 초과했습니다.', { type: body.type, current, max: MAX_CARDS })
  }
  verifyPin(account.id, body.accountPin)

  const requestedAt = nowIso()
  const granted = body.type === 'credit' ? INCOME_LIMIT[body.incomeRange!] : null
  let response: CardApplicationResult
  if (body.type === 'credit' && granted === null) {
    response = {
      id: `app_${++st.seq}`, type: body.type, status: 'rejected', requestedAt, grantedLimit: null,
      rejectReason: 'INCOME_INSUFFICIENT', card: null, estimatedDeliveryBusinessDays: null,
    }
  } else {
    const used = new Set(st.cards.map((c) => c.last4))
    let last4 = ''
    do last4 = pad(Math.floor(Math.random() * 10000)).padStart(4, '0')
    while (used.has(last4))
    const issuedAt = today()
    const [y, m] = parseDate(issuedAt)
    const product = PRODUCTS.find((p) => p.id === body.productId)!
    const card: CardRow = {
      id: `card_${String(5 + ++st.seq).padStart(3, '0')}`, name: product.name, type: body.type, last4,
      expiry: `${pad(m)}/${String((y + 5) % 100).padStart(2, '0')}`, status: 'active', issuedAt,
      accountId: account.id, paymentDay: body.type === 'credit' ? (body.paymentDay ?? 25) : null,
      creditLimit: granted, debitLimit: body.type === 'debit' ? { perTx: 1_000_000, perDay: 3_000_000 } : null,
      suspendedAt: null, lostAt: null, lostReason: null, terminatedAt: null, terminatedReason: null,
    }
    st.cards.push(card)
    const detail = toDetail(card)
    response = {
      id: `app_${st.seq}`, type: body.type, status: 'approved', requestedAt, grantedLimit: granted, rejectReason: null,
      card: {
        id: card.id, name: card.name, type: card.type, numberMasked: detail.numberMasked, expiry: card.expiry,
        status: 'active', issuedAt, paymentAccount: detail.paymentAccount, paymentDay: card.paymentDay,
        limit: detail.limit, debitLimit: card.debitLimit,
      },
      estimatedDeliveryBusinessDays: { min: 3, max: 5 },
    }
  }
  st.idem.set(idempotencyKey!, { fingerprint, response })
  return response
}

// ---------- 07 해지 ----------
const checkOf = (c: CardRow): TerminationCheck => {
  if (c.type === 'debit') return { cardId: c.id, canTerminate: true, blockReason: null, unpaidAmount: 0, firstDueDate: null }
  const totals = totalsOf(c)
  const unpaid = usedAmount(totals, today())
  return {
    cardId: c.id, canTerminate: unpaid === 0, blockReason: unpaid === 0 ? null : 'UNPAID_BALANCE',
    unpaidAmount: unpaid, firstDueDate: unpaid === 0 ? null : firstDueDate(totals, today()),
  }
}

const notTerminated = (c: CardRow) => {
  if (c.status === 'terminated') {
    throw fail(409, 'CARD_STATE_INVALID', '이미 해지된 카드입니다.', {
      currentStatus: c.status, allowedStatuses: ['active', 'suspended', 'lost'],
    })
  }
}

export async function checkTermination(cardId: string): Promise<TerminationCheck> {
  await delay()
  const c = findCard(cardId)
  notTerminated(c)
  return checkOf(c)
}

const REASONS = ['unused', 'benefit_complaint', 'other_card', 'lost_cleanup', 'other']

export async function terminateCard(cardId: string, body: TerminateRequest): Promise<TerminateResult> {
  await delay()
  const fields: FieldError[] = []
  if (body.reason != null && !REASONS.includes(body.reason)) fields.push({ field: 'reason', reason: 'INVALID_ENUM' })
  if (body.acknowledged === undefined) fields.push({ field: 'acknowledged', reason: 'REQUIRED' })
  else if (body.acknowledged !== true) fields.push({ field: 'acknowledged', reason: 'MUST_BE_TRUE' })
  fields.push(...pinFieldErrors(body.accountPin))
  if (fields.length) throw validation(fields)
  const c = findCard(cardId)
  notTerminated(c)
  const check = checkOf(c)
  if (!check.canTerminate) {
    throw fail(409, 'CARD_TERMINATE_BLOCKED_UNPAID', '미결제 금액이 있어 해지할 수 없습니다.', {
      unpaidAmount: check.unpaidAmount, firstDueDate: check.firstDueDate,
    })
  }
  verifyPin(c.accountId, body.accountPin)
  c.status = 'terminated'
  c.suspendedAt = null
  c.terminatedAt = nowIso()
  c.terminatedReason = body.reason ?? null
  return { id: c.id, status: 'terminated', terminatedAt: c.terminatedAt }
}

// ---------- 데모 제어 (콘솔에서 window.__cardMock 으로 사용) ----------
export const mock = {
  reset: () => {
    st = fresh()
    resetClock()
  },
  setNow,
  advance,
}

if (typeof window !== 'undefined') (window as unknown as { __cardMock: typeof mock }).__cardMock = mock
