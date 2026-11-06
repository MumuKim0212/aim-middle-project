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
  } else if (e.intent === 'income' && e.income) {
    const r = e.income
    badge = { label: '수입 기록', held: false }
    rows = [['날짜', r.when], ['수입 이름', r.source], ['금액', won(r.amount)], ['계좌 잔액', won(m.balance)], ['카드대금 반영 후 예상', won(m.projected)]]
  } else if (e.intent === 'daily' && s.daily) {
    const d = s.daily
    rows = [['오늘 더 쓸 수 있는 돈', won(Math.max(0, d.left)), d.left < 0 ? 'bad' : undefined], ['오늘 쓴 돈', won(d.todaySpent)], ['하루 기준 금액', won(d.allowance)]]
  } else if (e.intent === 'record' && e.recorded) {
    const r = e.recorded
    badge = { label: '기록 완료', held: false }
    rows = [['날짜', r.when], ['분류', r.category], ['금액', won(r.amount)], ['남은 월 예산', won(m.remaining)]]
  } else if (e.intent === 'week' && e.week) {
    const w = e.week
    rows = [
      ['이번 주 지출', won(w.spent)],
      ['가장 많이 쓴 항목', `${w.topName} ${won(w.topAmount)}`],
    ]
    if (w.hasPrev) rows.push(['지난주 같은 기간 대비', `${w.delta >= 0 ? '+' : '−'}${won(Math.abs(w.delta))}`, w.delta > 0 ? 'bad' : undefined])
  } else if (e.intent === 'category' && e.catSpent) {
    const c = e.catSpent
    rows = [[`이번 달 ${c.category} 지출`, won(c.spent)]]
    if (c.budget !== null) rows.push([`${c.category} 예산`, won(c.budget)], ['남은 예산', won(c.remaining ?? 0), (c.remaining ?? 0) < 0 ? 'bad' : undefined])
  } else if (e.intent === 'balance') {
    rows = [['계좌 잔액', won(m.balance)], ['카드대금 반영 후 예상', won(m.projected)]]
  } else if (e.intent === 'budget') {
    rows = [['이번 달 남은 예산', won(m.remaining)], ['쓴 돈 / 월 예산', `${won(m.spent)} / ${won(m.budget)}`]]
    for (const c of s.categories) {
      if (c.budget !== null && c.remaining !== null) rows.push([`${c.category} 예산 남음`, won(c.remaining), c.remaining < 0 ? 'bad' : undefined])
    }
  }

  const q = e.intent === 'query' ? e.query : null

  return (
    <div className="lg-card">
      {badge && <span className={badge.held ? 'lg-badge held' : 'lg-badge ok'}>{badge.label}</span>}
      <p>{text}</p>
      {q && q.ok && q.rows.length > 0 && (
        <div className="lg-qtable">
          <table>
            <thead><tr>{q.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {q.rows.map((r, i) => (
                <tr key={i}>{r.map((v, j) => <td key={j}>{typeof v === 'number' ? v.toLocaleString('ko-KR') : v ?? '—'}</td>)}</tr>
              ))}
            </tbody>
          </table>
          {q.total > q.rows.length && <small>앞의 {q.rows.length}행만 보여 줘요 (전체 {q.total}행)</small>}
        </div>
      )}
      {q && q.ok && q.sql && (
        <details className="lg-qsql">
          <summary>이렇게 계산했어요</summary>
          <p>{q.basis}</p>
          <code>{q.sql}</code>
        </details>
      )}
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
