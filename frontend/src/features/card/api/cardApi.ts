// 카드 API 클라이언트. 화면은 이 파일의 함수만 부른다 (docs/dev/card/frontend-spec.md 3.3절).
import { request } from './http'
import type {
  ApplyEligibility, CardApplicationRequest, CardApplicationResult, CardDetail, CardLimit, CardListResponse,
  CardProduct, CardStatusResult, PaymentAccount, TerminateRequest, TerminateResult, TerminationCheck,
  TransactionDetail, TransactionListParams, TransactionListResponse, UpcomingBilling,
} from './types'

const enc = encodeURIComponent

export const listCards = (opts: { includeTerminated?: boolean } = {}) =>
  request<CardListResponse>('GET', '/cards', { query: { includeTerminated: opts.includeTerminated } })

export const getCard = (cardId: string) => request<CardDetail>('GET', `/cards/${enc(cardId)}`)

export const listTransactions = (p: TransactionListParams) =>
  request<TransactionListResponse>('GET', '/card-transactions', { query: { ...p } })

export const getTransaction = (id: string) => request<TransactionDetail>('GET', `/card-transactions/${enc(id)}`)

export const getUpcomingBilling = () => request<UpcomingBilling>('GET', '/card-billing/upcoming')

export const suspendCard = (cardId: string, accountPin: string) =>
  request<CardStatusResult>('POST', `/cards/${enc(cardId)}/suspend`, { body: { accountPin } })

export const resumeCard = (cardId: string, accountPin: string) =>
  request<CardStatusResult>('POST', `/cards/${enc(cardId)}/resume`, { body: { accountPin } })

export const reportLost = (cardId: string, body: { reason: 'lost' | 'stolen'; accountPin: string }) =>
  request<CardStatusResult>('POST', `/cards/${enc(cardId)}/report-lost`, { body })

export const getCardLimit = (cardId: string) => request<CardLimit>('GET', `/cards/${enc(cardId)}/limit`)

export const listCardProducts = () => request<{ items: CardProduct[] }>('GET', '/card-products')

export const listPaymentAccounts = () =>
  request<{ items: PaymentAccount[] }>('GET', '/accounts', { query: { purpose: 'card_payment' } })

export const getApplyEligibility = () => request<ApplyEligibility>('GET', '/card-applications/eligibility')

export const applyCard = (body: CardApplicationRequest, idempotencyKey?: string) =>
  request<CardApplicationResult>('POST', '/card-applications', {
    body,
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
  })

export const checkTermination = (cardId: string) =>
  request<TerminationCheck>('GET', `/cards/${enc(cardId)}/termination-check`)

export const terminateCard = (cardId: string, body: TerminateRequest) =>
  request<TerminateResult>('POST', `/cards/${enc(cardId)}/terminate`, { body })
