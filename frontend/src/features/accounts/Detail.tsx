import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { dDay, shortDate, won } from '../../format'
import { callJson } from '../../lib/http'
import { STATUS } from './AccountList'
import { accountName, errCode, errMsg, TYPE_LABEL, useLoad, type AccountDetail } from './api'
import { LoadState } from './parts'

/** A-04 계좌 상세. 저축예금은 입금·이체, 예적금은 이자·만기·(적금) 자동이체와 납입. */
export default function Detail() {
  const id = useParams().id
  const { data: a, error, reload } = useLoad<AccountDetail>(`/api/accounts/${id}`)
  const flash = (useLocation().state as { flash?: string } | null)?.flash
  const [msg, setMsg] = useState<string | null>(null)
  if (!a) return <LoadState error={error} retry={reload} />

  const active = a.status === 'active'
  const checking = a.productType === 'checking'
  const savings = a.productType === 'savings'
  const d = a.maturityDate && active ? dDay(a.maturityDate) : null

  async function act(fn: () => Promise<unknown>) {
    setMsg(null)
    try { await fn(); reload() } catch (x) { setMsg(errMsg(x)) }
  }

  return (
    <section className="ac-page">
      {(flash || msg) && <p className={msg ? 'auth-err' : 'auth-flash'} role="status">{msg ?? flash}</p>}
      <div className="asset-card">
        <p className="hello">{TYPE_LABEL[a.productType]}{a.isPrimary && <em className="chip-mini">대표</em>}{!active && <em className="chip-mini">{STATUS[a.status]}</em>}</p>
        <p className="label">{accountName(a)}</p>
        <p className="big">{won(a.balance)}</p>
        <p className="ac-no">{a.bankName} {a.accountNo} <CopyButton text={a.accountNo} /></p>
      </div>

      {a.isMatured && (
        <div className="ac-banner">
          <strong>만기가 되었습니다.</strong> 해지하여 원리금을 받으세요.
          <Link to={`/accounts/${a.accountId}/close`} className="ac-link-btn">해지하기</Link>
        </div>
      )}

      <dl className="auth-summary">
        <div><dt>금리</dt><dd>연 {a.rate.toFixed(1)}%{checking && ' (표시만)'}</dd></div>
        <div><dt>개설일</dt><dd>{a.openedAt.replace(/-/g, '.')}</dd></div>
        {a.maturityDate && <div><dt>만기일</dt><dd>{a.maturityDate.replace(/-/g, '.')}{d !== null && ` (${d > 0 ? `D-${d}` : d === 0 ? '오늘' : '지남'})`}</dd></div>}
        {savings && <div><dt>월 납입액</dt><dd>{won(a.monthlyAmount ?? 0)} (매월 {a.paymentDay}일)</dd></div>}
        {savings && <div><dt>납입 회차</dt><dd>{a.paidCount}/{a.termMonths}회차{a.unpaidRound && <b className="ac-warn"> · {a.unpaidRound}회차 미납</b>}</dd></div>}
        {savings && active && <div><dt>자동이체</dt><dd>{a.autoPay ? `켜짐 (매월 ${a.paymentDay}일${a.linkedAccountMasked ? `, ${a.linkedAccountMasked}` : ''})` : '꺼짐'}</dd></div>}
        {!checking && a.linkedAccountMasked && <div><dt>납입·만기 입금 계좌</dt><dd>{a.linkedAccountMasked}</dd></div>}
      </dl>

      {a.interest && (
        <div className="card ac-interest">
          <h3>이자 (세전)</h3>
          <div className="two">
            <div className="mini"><small>지금까지 쌓인 이자</small><b>{won(a.interest.accrued)}</b></div>
            <div className="mini"><small>만기 예상 이자</small><b>{won(a.interest.atMaturity)}</b></div>
          </div>
          <p className="small">지금 해지하면 {a.interest.closeNow.kind === 'early' ? `중도해지 금리 연 ${a.interest.closeNow.rate.toFixed(1)}%로 ` : '약정 금리로 '}
            이자 {won(a.interest.closeNow.interest)}, 받을 금액 {won(a.interest.closeNow.total)}</p>
        </div>
      )}

      {active && savings && (
        <button type="button" className="auth-btn" onClick={() => void act(() => callJson('POST', `/api/accounts/${a.accountId}/auto-pay`, { enabled: !a.autoPay }))}>
          자동이체 {a.autoPay ? '끄기' : '켜기'}
        </button>
      )}

      <div className="ac-actions">
        {active && checking && <Link to={`/accounts/${a.accountId}/deposit`}>입금</Link>}
        {active && checking && <Link to={`/transfer?from=${a.accountId}`}>이체</Link>}
        {active && savings && <Link to={`/accounts/${a.accountId}/pay`}>납입하기</Link>}
        <Link to={`/accounts/${a.accountId}/transactions`}>거래내역</Link>
        {active && <Link to={`/accounts/${a.accountId}/close`} className="danger">해지</Link>}
      </div>

      {a.devTools && active && !checking && (
        <div className="ac-dev">
          <small>개발 모드 시연</small>
          <button type="button" onClick={() => void act(() => callJson('POST', `/api/dev/accounts/${a.accountId}/maturity`))}>만기 도래 시뮬레이션</button>
          {savings && <button type="button" onClick={() => void act(() => callJson('POST', '/api/dev/auto-pay/run'))}>자동이체 실행</button>}
        </div>
      )}
    </section>
  )
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return <button type="button" className="ac-copy" onClick={() => { void navigator.clipboard?.writeText(text); setDone(true); window.setTimeout(() => setDone(false), 1500) }}>{done ? '복사됨' : '복사'}</button>
}

/** A-07 적금 납입: 이번 회차, 자동이체 상태, 미납 회차, 출금 저축예금 잔액. 이미 낸 달이면 막는다. */
export function Pay() {
  const id = useParams().id
  const nav = useNavigate()
  const { data: a, error, reload } = useLoad<AccountDetail>(`/api/accounts/${id}`)
  const src = useLoad<AccountDetail>(a?.linkedAccountId ? `/api/accounts/${a.linkedAccountId}` : null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!a || (a.linkedAccountId && !src.data)) return <LoadState error={error ?? src.error} retry={() => { reload(); src.reload() }} />
  if (a.productType !== 'savings' || a.status !== 'active') return <div className="state">납입할 수 있는 정기적금이 아니에요.</div>

  const done = a.paidThisMonth || (a.paidCount ?? 0) >= (a.termMonths ?? 12)
  const short = !!src.data && src.data.balance < (a.monthlyAmount ?? 0)

  async function pay() {
    setBusy(true); setErr(null)
    try {
      await callJson('POST', `/api/accounts/${a!.accountId}/pay`)
      nav(`/accounts/${a!.accountId}`, { replace: true, state: { flash: `${won(a!.monthlyAmount ?? 0)}을 납입했어요.` } })
    } catch (x) {
      setErr(errMsg(x))
      if (errCode(x) === 'SAVINGS_ALREADY_PAID') reload()
    } finally { setBusy(false) }
  }

  return (
    <section className="auth-page">
      <h2 className="auth-title">{accountName(a)} 납입</h2>
      <dl className="auth-summary">
        <div><dt>이번 회차</dt><dd>{Math.min((a.paidCount ?? 0) + 1, a.termMonths ?? 12)}/{a.termMonths}회차 · 납입일 {a.nextDueDate ? shortDate(a.nextDueDate) : '—'}</dd></div>
        <div><dt>자동이체</dt><dd>{a.autoPay ? `켜짐 (매월 ${a.paymentDay}일)` : '꺼짐'}</dd></div>
        <div><dt>월 납입액</dt><dd>{won(a.monthlyAmount ?? 0)}</dd></div>
        {src.data && <div><dt>출금 계좌 잔액</dt><dd>{accountName(src.data)} {won(src.data.balance)}</dd></div>}
      </dl>
      {a.unpaidRound && <p className="auth-err" role="status">{a.unpaidRound}회차가 미납이에요. 지금 납입할 수 있어요.</p>}
      {done && <p className="auth-notice" role="status">{(a.paidCount ?? 0) >= (a.termMonths ?? 12) ? '12회차를 모두 납입했어요.' : '이번 달은 납입이 완료되었습니다.'}</p>}
      {short && !done && <p className="auth-err" role="alert">출금 계좌 잔액이 부족합니다.</p>}
      {err && <p className="auth-err" role="alert">{err}</p>}
      <div className="auth-actions">
        <button type="button" className="ghost" onClick={() => nav(-1)}>뒤로</button>
        <button type="button" className="primary" disabled={done || short || busy} onClick={() => void pay()}>납입하기</button>
      </div>
    </section>
  )
}
