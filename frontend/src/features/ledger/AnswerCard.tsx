import { won } from '../../format'
import type { Summary } from './api'
import { metrics, type Entry } from './copy'

type Row = [label: string, value: string, tone?: 'bad']

/** 답변을 단락으로 나눈다: 판정 배지 → 숫자 카드 → 말투가 들어간 한마디. 숫자는 서버가 확정한 값만 쓴다. */
export default function AnswerCard({ entry: e, summary: s, text }: { entry: Entry; summary: Summary; text: string }) {
  const m = metrics(s)
  let badge: { label: string; held: boolean } | null = null
  let rows: Row[] = []

  if (e.intent === 'purchase' && e.check) {
    const c = e.check
    const held = c.result === 'held'
    badge = { label: held ? '결제 보류' : '결제 가능', held }
    rows = [
      [`${c.category} 결제 금액`, won(c.amount)],
      ['결제 후 월 예산 남음', won(c.after.budgetRemaining), c.after.budgetRemaining < 0 ? 'bad' : undefined],
      ['결제 후 예상 잔액', won(c.after.expectedBalance), c.after.expectedBalance < 0 ? 'bad' : undefined],
    ]
    if (c.after.categoryRemaining !== null) rows.push([`결제 후 ${c.category} 예산 남음`, won(c.after.categoryRemaining), c.after.categoryRemaining < 0 ? 'bad' : undefined])
    if (held && c.overAmount > 0) rows.push(['초과 금액', won(c.overAmount), 'bad'])
  } else if ((e.intent === 'last' || e.intent === 'prev2') && e.history) {
    const h = e.history
    rows = [
      [`${h.month} 지출`, won(h.spent)],
      ['전월 대비', `${h.delta >= 0 ? '+' : '−'}${won(Math.abs(h.delta))}`, h.delta > 0 ? 'bad' : undefined],
      ['가장 많이 쓴 항목', `${h.topName} ${won(h.topAmount)}`],
    ]
  } else if (e.intent === 'balance') {
    rows = [['계좌 잔액', won(m.balance)], ['카드대금 반영 후 예상', won(m.projected)]]
  } else if (e.intent === 'budget') {
    rows = [['이번 달 남은 예산', won(m.remaining)], ['쓴 돈 / 월 예산', `${won(m.spent)} / ${won(m.budget)}`]]
  }

  return (
    <div className="lg-card">
      {badge && <span className={badge.held ? 'lg-badge held' : 'lg-badge ok'}>{badge.label}</span>}
      <p>{text}</p>
      {rows.length > 0 && (
        <dl>
          {rows.map(([k, v, tone]) => (
            <div key={k}><dt>{k}</dt><dd className={tone}>{v}</dd></div>
          ))}
        </dl>
      )}
    </div>
  )
}
