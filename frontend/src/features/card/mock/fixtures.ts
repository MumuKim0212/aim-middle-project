// docs/card/00-api-common.md 10절 기준 데이터 (member_001 몫만).
import type { CardStatus, CardType, DebitLimit } from '../api/types'
import type { Tx } from '../lib/cycles'
import { pad } from '../lib/dates'

export type AccountRow = {
  id: string
  bankName: string
  masked: string
  balance: number
  pin: string
}

export type CardRow = {
  id: string
  name: string
  type: CardType
  last4: string
  expiry: string
  status: CardStatus
  issuedAt: string
  accountId: string
  paymentDay: number | null
  creditLimit: number | null
  debitLimit: DebitLimit | null
  suspendedAt: string | null
  lostAt: string | null
  lostReason: 'lost' | 'stolen' | null
  terminatedAt: string | null
  terminatedReason: string | null
}

export const MEMBER_BIRTH_DATE = '1990-05-15'

export const accountFixtures: AccountRow[] = [
  { id: 'acc_001', bankName: 'AIM Bank', masked: '****1234', balance: 2_000_000, pin: '1234' },
  { id: 'acc_002', bankName: 'AIM Bank', masked: '****5678', balance: 50_000, pin: '1234' },
]

const DEBIT_LIMIT: DebitLimit = { perTx: 1_000_000, perDay: 3_000_000 }

const base = {
  suspendedAt: null,
  lostAt: null,
  lostReason: null,
  terminatedAt: null,
  terminatedReason: null,
}

export const cardFixtures: CardRow[] = [
  {
    ...base, id: 'card_001', name: 'AIM 체크카드', type: 'debit', last4: '1111', expiry: '03/30',
    status: 'active', issuedAt: '2025-03-10', accountId: 'acc_001', paymentDay: null,
    creditLimit: null, debitLimit: DEBIT_LIMIT,
  },
  {
    ...base, id: 'card_002', name: 'AIM 신용카드', type: 'credit', last4: '2222', expiry: '06/30',
    status: 'active', issuedAt: '2025-06-01', accountId: 'acc_002', paymentDay: 25,
    creditLimit: 3_000_000, debitLimit: null,
  },
  {
    ...base, id: 'card_003', name: 'AIM 신용카드', type: 'credit', last4: '3333', expiry: '09/30',
    status: 'suspended', issuedAt: '2025-09-20', accountId: 'acc_001', paymentDay: 10,
    creditLimit: 1_000_000, debitLimit: null, suspendedAt: '2026-10-30T14:05:00+09:00',
  },
  {
    ...base, id: 'card_004', name: 'AIM 신용카드', type: 'credit', last4: '4444', expiry: '01/31',
    status: 'lost', issuedAt: '2026-01-05', accountId: 'acc_001', paymentDay: 25,
    creditLimit: 500_000, debitLimit: null, lostAt: '2026-10-20T11:30:00+09:00', lostReason: 'lost',
  },
  {
    ...base, id: 'card_005', name: 'AIM 체크카드', type: 'debit', last4: '5555', expiry: '08/29',
    status: 'terminated', issuedAt: '2024-08-30', accountId: 'acc_001', paymentDay: null,
    creditLimit: null, debitLimit: DEBIT_LIMIT, terminatedAt: '2026-08-30T10:00:00+09:00',
  },
]

const tx = (
  id: string, cardId: string, iso: string, merchant: string, amount: number,
  kind: 'approval' | 'cancel' = 'approval', installmentMonths = 0, originalId: string | null = null,
): Tx => ({ id, cardId, ts: Date.parse(iso), occurredAt: iso, merchant, amount, kind, originalId, installmentMonths })

export const txFixtures = (): Tx[] => {
  const convenience = Array.from({ length: 30 }, (_, i) => {
    const n = i + 1
    return tx(`tx_1${pad(n)}`, 'card_001', `2026-10-${pad(n)}T12:00:00+09:00`, `편의점 ${n}호점`, n * 1000)
  })
  return [
    ...convenience,
    tx('tx_205', 'card_002', '2026-08-10T15:40:00+09:00', '삼성전자', 900_000, 'approval', 3),
    tx('tx_201', 'card_002', '2026-09-12T13:10:00+09:00', '이마트', 120_000),
    tx('tx_202', 'card_002', '2026-10-05T12:20:00+09:00', '쿠팡', 300_000),
    tx('tx_203', 'card_002', '2026-10-18T09:05:00+09:00', '스타벅스 강남점', 12_000),
    tx('tx_204', 'card_002', '2026-10-22T10:15:00+09:00', '스타벅스 강남점', 12_000, 'cancel', 0, 'tx_203'),
    tx('tx_206', 'card_002', '2026-10-30T19:30:00+09:00', '현대백화점', 600_000, 'approval', 2),
    tx('tx_207', 'card_002', '2026-11-02T08:10:00+09:00', 'GS25', 8_000),
    tx('tx_401', 'card_004', '2026-10-15T20:00:00+09:00', '올리브영', 45_000),
  ]
}
