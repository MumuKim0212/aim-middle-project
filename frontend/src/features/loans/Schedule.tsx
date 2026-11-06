import { useParams } from 'react-router-dom'
import { won } from '../../format'
import { useLoad } from '../accounts/api'
import type { Schedule } from './api'
import { LoanLoad } from './parts'

/** 상환 일정: 지금 잔액에서 0원이 될 때까지 남은 회차 전부. */
export default function LoanSchedule() {
  const no = useParams().no
  const { data, error, reload } = useLoad<Schedule>(`/api/loans/${no}/schedule`)
  if (!data) return <LoanLoad error={error} retry={reload} />

  return (
    <section className="ac-page">
      <h2 className="auth-title">상환 일정</h2>
      <dl className="auth-summary">
        <div><dt>납입 완료</dt><dd>{data.paid}회</dd></div>
        <div><dt>남은 회차</dt><dd>{data.rows.length}회</dd></div>
        <div><dt>남은 원금 합계</dt><dd>{won(data.principalSum)}</dd></div>
        <div><dt>남은 이자 합계</dt><dd>{won(data.interestSum)}</dd></div>
      </dl>
      {data.rows.length === 0
        ? <p className="ac-empty">남은 상환 일정이 없어요.</p>
        : (
          <ul className="ac-tx">
            {data.rows.map((r) => (
              <li key={r.seq}>
                <div><strong>{r.seq}회차</strong><small>{r.dueDate.replace(/-/g, '.')}</small></div>
                <div className="ac-tx-amt">
                  <b>{won(r.principal + r.interest)}</b>
                  <small>원금 {won(r.principal)} · 이자 {won(r.interest)}</small>
                  <small>남은 잔액 {won(r.balanceAfter)}</small>
                </div>
              </li>
            ))}
          </ul>
        )}
    </section>
  )
}
