// API 응답·요청 타입. docs/dev/card/frontend-spec.md 3.4절과 같다.
export type CardType = 'credit' | 'debit'
export type CardStatus = 'active' | 'suspended' | 'lost' | 'terminated'
export type CardAction =
  | 'view_transactions'
  | 'view_limit'
  | 'suspend'
  | 'resume'
  | 'report_lost'
  | 'terminate'

export type PaymentAccount = { accountId: number; bankName: string; accountMasked: string }
export type CreditLimit = { total: number; used: number; remaining: number; usageRate: number }
export type DebitLimit = { perTx: number; perDay: number }

export type CardSummary = {
  id: string
  name: string
  type: CardType
  numberMasked: string
  status: CardStatus
  issuedAt: string
  terminatedAt: string | null
}
export type CardListResponse = { items: CardSummary[]; terminatedCount: number }

export type CardDetail = {
  id: string
  name: string
  type: CardType
  numberMasked: string
  expiry: string
  status: CardStatus
  issuedAt: string
  paymentAccount: PaymentAccount
  paymentDay: number | null
  limit: CreditLimit | null
  debitLimit: DebitLimit | null
  suspendedAt: string | null
  lostAt: string | null
  lostReason: 'lost' | 'stolen' | null
  terminatedAt: string | null
  availableActions: CardAction[]
}

export type CardStatusResult = {
  id: string
  status: CardStatus
  suspendedAt: string | null
  lostAt: string | null
  lostReason: 'lost' | 'stolen' | null
}

export type TransactionKind = 'approval' | 'cancel'
export type TransactionItem = {
  id: string
  cardId: string
  cardName: string
  cardType: CardType
  cardNumberLast4: string
  occurredAt: string
  merchant: string
  amount: number
  kind: TransactionKind
  originalId: string | null
  installmentMonths: number
}
export type TransactionDetail = TransactionItem & {
  original: { id: string; occurredAt: string; merchant: string; amount: number } | null
}
export type TransactionListParams = {
  cardId?: string
  from: string
  to: string
  kind?: 'all' | 'approval' | 'cancel'
  merchant?: string
  limit?: number
  cursor?: string
}
export type TransactionSummary = {
  approvalTotal: number
  cancelTotal: number
  netTotal: number
  count: number
}
export type TransactionListResponse = {
  summary: TransactionSummary
  items: TransactionItem[]
  nextCursor: string | null
}

export type BillingItem = {
  kind: 'approval' | 'cancel' | 'installment'
  occurredAt: string
  merchant: string
  amount: number
  installment: { round: number; months: number } | null
}
export type BillingCard = {
  cardId: string
  cardName: string
  status: 'active' | 'suspended' | 'lost'
  cardNumberLast4: string
  amount: number
  usagePeriod: { from: string; to: string }
  items: BillingItem[]
}
export type BillingPayment = {
  paymentDate: string
  isCurrentMonth: boolean
  paymentAccount: PaymentAccount
  amount: number
  balance: number | null
  balanceStatus: 'ok' | 'insufficient' | 'unavailable'
  shortfall: number | null
  cards: BillingCard[]
}
export type UpcomingBilling = {
  asOf: string
  hasCreditCard: boolean
  thisMonthTotal: number
  nextPaymentDate: string | null
  daysUntilPayment: number | null
  payments: BillingPayment[]
}

export type CardLimit = {
  cardId: string
  type: CardType
  status: CardStatus
  credit: CreditLimit | null
  debit: DebitLimit | null
}

export type CardProduct = { id: string; type: CardType; name: string; description: string }
export type ApplyEligibility = {
  types: Record<
    CardType,
    {
      available: boolean
      reason: 'AGE_UNDER_19' | 'COUNT_EXCEEDED' | null
      currentCount: number
      maxCount: number
    }
  >
}
export type IncomeRange = 'none' | 'lt_10m' | '10m_20m' | '20m_40m' | '40m_70m' | 'gte_70m'
export type CardApplicationRequest = {
  type: CardType
  productId: string
  paymentAccountId: number
  paymentDay?: number
  incomeRange?: IncomeRange
  cardPin: string
  recipient: string
  phone: string
  address: { line1: string; line2?: string }
  agreements: { cardTerms: boolean; privacy: boolean; creditInquiry?: boolean }
}
export type IssuedCard = {
  id: string
  name: string
  type: CardType
  numberMasked: string
  expiry: string
  status: 'active'
  issuedAt: string
  paymentAccount: PaymentAccount
  paymentDay: number | null
  limit: CreditLimit | null
  debitLimit: DebitLimit | null
}
export type CardApplicationResult = {
  id: string
  type: CardType
  status: 'approved' | 'rejected'
  requestedAt: string
  grantedLimit: number | null
  rejectReason: 'INCOME_INSUFFICIENT' | null
  card: IssuedCard | null
  estimatedDeliveryBusinessDays: { min: number; max: number } | null
}

export type TerminationCheck = {
  cardId: string
  canTerminate: boolean
  blockReason: 'UNPAID_BALANCE' | null
  unpaidAmount: number
  firstDueDate: string | null
}
export type TerminateReason =
  | 'unused'
  | 'benefit_complaint'
  | 'other_card'
  | 'lost_cleanup'
  | 'other'
export type TerminateRequest = {
  reason?: TerminateReason | null
  acknowledged: true
}
export type TerminateResult = { id: string; status: 'terminated'; terminatedAt: string }
