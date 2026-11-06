import { useCallback, useEffect, useState } from 'react'
import { ApiFail, callJson } from '../../lib/http'

// 계좌 API 응답 타입(backend/app/accounts/service.py 와 맞춘다)
export type ProductType = 'checking' | 'deposit' | 'savings'

export type Account = {
  accountId: number
  bankName: string
  accountMasked: string
  balance: number
  productType: ProductType
  productName: string
  status: 'active' | 'matured' | 'closed_early' | 'closed'
  alias: string | null
  isPrimary: boolean
  rate: number
  openedAt: string
  maturityDate: string | null
  termMonths: number | null
  monthlyAmount: number | null
  paymentDay: number | null
  paidCount: number | null
  autoPay: boolean | null
}

export type CloseNow = { kind: 'matured' | 'early'; rate: number; interest: number; principal: number; total: number }

export type AccountDetail = Account & {
  accountNo: string
  earlyCloseRate: number | null
  linkedAccountId: number | null
  linkedAccountMasked: string | null
  closedAt: string | null
  interest: { accrued: number; atMaturity: number; closeNow: CloseNow } | null
  isMatured: boolean
  unpaidRound: number | null
  nextDueDate: string | null
  paidThisMonth: boolean | null
  devTools: boolean
}

export type Product = {
  id: number
  type: ProductType
  name: string
  description: string | null
  rate: number
  earlyCloseRate: number | null
  minAmount: number | null
  maxAmount: number | null
  minMonths: number | null
  maxMonths: number | null
  maxPerUser: number | null
  requiresChecking: boolean
}

export type Tx = {
  id: number
  type: string
  direction: 'in' | 'out' | null
  amount: number
  balanceAfter: number
  counterpartyName: string | null
  memo: string | null
  refType: string | null
  refId: string | null
  createdAt: string
}

export type ClosePreview =
  | { productType: 'checking'; balance: number; blocker: { code: string; message: string } | null }
  | {
      productType: 'deposit' | 'savings'
      kind: 'matured' | 'early'
      principal: number
      openedAt: string
      maturityDate: string
      elapsedDays: number
      appliedRate: number
      contractRate: number
      interest: number
      total: number
      receivingAccountId: number | null
    }

export const TYPE_LABEL: Record<ProductType, string> = { checking: '저축예금', deposit: '정기예금', savings: '정기적금' }
export const accountName = (a: Pick<Account, 'alias' | 'productName'>) => a.alias || a.productName

/** 서버가 준 문구를 그대로 보여 준다(없으면 기본 문구). 분기는 code 로 한다. */
export const errMsg = (e: unknown) => (e instanceof ApiFail && e.body.message) || '요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.'
export const errCode = (e: unknown) => (e instanceof ApiFail ? e.code : undefined)

/** GET 조회 훅. 로딩·실패(다시 시도)는 호출한 화면이 LoadState 로 보여 준다. */
export function useLoad<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!url) return
    let alive = true
    setError(null)
    callJson<T>('GET', url).then((d) => alive && setData(d)).catch((e) => alive && setError(e))
    return () => { alive = false }
  }, [url, tick])
  const reload = useCallback(() => { setData(null); setTick((n) => n + 1) }, [])
  return { data, error, reload }
}

const DIGIT = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']
const UNIT = ['', '십', '백', '천']
const four = (n: number) => [3, 2, 1, 0].map((i) => {
  const d = Math.floor(n / 10 ** i) % 10
  return d ? (d === 1 && i > 0 ? '' : DIGIT[d]) + UNIT[i] : ''
}).join('')

/** 10000 → "일만원", 1234000 → "백이십삼만 사천원" (금액 입력 화면에서 같이 보여 준다) */
export function hangulAmount(n: number): string {
  if (!n) return ''
  const parts = [[Math.floor(n / 100_000_000), '억'], [Math.floor(n / 10_000) % 10_000, '만'], [n % 10_000, '']] as const
  return parts.filter(([v]) => v).map(([v, u]) => four(v) + u).join(' ') + '원'
}
