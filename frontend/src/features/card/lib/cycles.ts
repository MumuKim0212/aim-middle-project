// 청구 주기 계산. docs/card/00-api-common.md 6절 구현.
import { dateOf, kstDate, parseDate } from './dates'

export type Tx = {
  id: string
  cardId: string
  ts: number
  occurredAt: string
  merchant: string
  amount: number
  kind: 'approval' | 'cancel'
  originalId: string | null
  installmentMonths: number
}

export type CycleLine = {
  cycle: string
  kind: 'approval' | 'cancel' | 'installment'
  tx: Tx
  amount: number
  installment: { round: number; months: number } | null
}

export const piece = (amount: number, n: number, i: number) =>
  i < n ? Math.floor(amount / n) : amount - Math.floor(amount / n) * (n - 1)

/** 거래 날짜가 속한 달의 다음 달 D일 */
const cycleOf = (date: string, d: number) => {
  const [y, m] = parseDate(date)
  return dateOf(y, m + 1, d)
}

/** 발생월에서 i개월 뒤의 D일 */
const dueOf = (date: string, d: number, i: number) => {
  const [y, m] = parseDate(date)
  return dateOf(y, m + i, d)
}

export const cycleLines = (txs: Tx[], d: number): CycleLine[] => {
  const byId = new Map(txs.map((t) => [t.id, t]))
  const lines: CycleLine[] = []
  for (const t of txs) {
    const date = kstDate(t.ts)
    if (t.kind === 'approval') {
      const n = t.installmentMonths
      if (n === 0) {
        lines.push({ cycle: cycleOf(date, d), kind: 'approval', tx: t, amount: t.amount, installment: null })
      } else {
        for (let i = 1; i <= n; i++) {
          lines.push({
            cycle: dueOf(date, d, i),
            kind: 'installment',
            tx: t,
            amount: piece(t.amount, n, i),
            installment: { round: i, months: n },
          })
        }
      }
    } else {
      const original = t.originalId ? byId.get(t.originalId) : undefined
      const originalCycle = cycleOf(original ? kstDate(original.ts) : date, d)
      // 취소 일자가 원 승인의 결제일(당일 포함) 이전이면 같은 주기에서 차감, 이후면 취소가 속한 주기에서 차감
      const cycle = date <= originalCycle ? originalCycle : cycleOf(date, d)
      lines.push({ cycle, kind: 'cancel', tx: t, amount: t.amount, installment: null })
    }
  }
  return lines
}

export const cycleTotals = (lines: CycleLine[]) => {
  const totals = new Map<string, number>()
  for (const l of lines) {
    totals.set(l.cycle, (totals.get(l.cycle) ?? 0) + (l.kind === 'cancel' ? -l.amount : l.amount))
  }
  return totals
}

/** B(P): 음수는 0, 이월 없음 */
export const billed = (totals: Map<string, number>, cycle: string) => Math.max(0, totals.get(cycle) ?? 0)

/** 결제일 당일까지는 미결제로 본다 (P >= today) */
export const usedAmount = (totals: Map<string, number>, today: string) => {
  let used = 0
  for (const [cycle, value] of totals) if (cycle >= today) used += Math.max(0, value)
  return used
}

export const usageRate = (used: number, total: number) =>
  Math.min(1000, Math.floor((used * 1000 + Math.floor(total / 2)) / total)) / 10

/** 오늘 이후(당일 포함) 가장 가까운 결제일 */
export const nextPaymentDate = (today: string, d: number) => {
  const [y, m, day] = parseDate(today)
  return d >= day ? dateOf(y, m, d) : dateOf(y, m + 1, d)
}

/** 미결제 청구가 처음 결제되는 날 (B(P) > 0 인 가장 빠른 P >= today) */
export const firstDueDate = (totals: Map<string, number>, today: string) => {
  const due = [...totals].filter(([c, v]) => c >= today && v > 0).map(([c]) => c)
  return due.length ? due.sort()[0] : null
}
