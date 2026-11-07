import { ApiFail, apiFetch, type ApiErrorBody } from '../../lib/http'

// 대출 API 응답 타입(backend/app/loan/router.py·management.py 와 맞춘다). 금액은 원 단위 정수, 날짜는 ISO 문자열.
export type LoanStatus = 'ACTIVE' | 'OVERDUE' | 'ACCELERATED' | 'WITHDRAWN' | 'PAID_OFF' | 'CLOSED'

export type Loan = {
  contractNo: string
  accountMasked: string
  productId: string
  status: LoanStatus
  principal: number
  balance: number
  rate: number
  termMonths: number
  repayMethod: string
  startDate: string
  nextDueDate: string | null
  debitAccountId: number | null
}

/** GET /api/loans 의 항목. 상세(GET /api/loans/{no})에는 상품 이름이 없다. */
export type LoanSummary = Loan & { productName: string }

export type LoanProduct = {
  productId: string
  businessType: 'GENERAL' | 'POLICY' | 'INST' | 'REFI'
  instKind: 'A' | 'B' | null
  collateralType: 'CREDIT' | 'JEONSE' | 'MORTGAGE' | 'AUTO' | 'DEPOSIT'
  name: string
  subtitle: string
  targetDesc: string
  minAmount: number
  maxAmount: number
  rateMin: number
  rateMax: number
  termOptions: number[]
  repayOptions: string[]
}

export type ScheduleRow = { seq: number; dueDate: string; principal: number; interest: number; balanceAfter: number }
export type Schedule = { paid: number; rows: ScheduleRow[]; principalSum: number; interestSum: number }

export type PrepayQuote = { principal: number; fee: number; interest: number; total: number; feeFree: boolean }
export type WithdrawResult = { accepted: boolean; deadline: string; refund: number }

export const STATUS_LABEL: Record<LoanStatus, string> = {
  ACTIVE: '정상', OVERDUE: '연체', ACCELERATED: '기한이익상실', WITHDRAWN: '청약철회', PAID_OFF: '완제', CLOSED: '종료',
}

/** 중도상환은 Idempotency-Key 헤더가 필요해서 callJson 대신 직접 보낸다. */
export async function prepay(no: string, body: { principal: number; accountId: number | null }, key: string) {
  const res = await apiFetch(`/api/loans/${no}/prepay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiFail(res.status, data as ApiErrorBody)
  return data as PrepayQuote & { balance: number }
}

/** 대출 실행도 Idempotency-Key 가 필요하다. 본문을 JSON 으로 보내고 실패하면 ApiFail 을 던진다. */
export async function postIdem<T>(url: string, body: unknown, key: string) {
  const res = await apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiFail(res.status, data as ApiErrorBody)
  return data as T
}

/** 증빙 파일 1건 업로드(multipart). Content-Type 은 브라우저가 경계값과 함께 정한다. */
export async function uploadDoc(id: string, docKey: string, file: File) {
  const form = new FormData()
  form.append('docKey', docKey)
  form.append('file', file)
  const res = await apiFetch(`/api/loans/applications/${id}/docs/upload`, { method: 'POST', body: form })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiFail(res.status, data as ApiErrorBody)
  return data as { docKey: string; defects: string[] }
}
