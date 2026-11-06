import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { won } from '../../format'
import { callJson } from '../../lib/http'
import { errMsg, useLoad, accountName, type AccountDetail } from './api'
import { AmountField, LoadState } from './parts'

const LIMIT = 10_000_000

/** A-06 입금(시연용 ATM 입금): 금액 입력 → 확인 → 잔액 증가. 저축예금만. */
export default function Deposit() {
  const id = useParams().id
  const nav = useNavigate()
  const { data: a, error, reload } = useLoad<AccountDetail>(`/api/accounts/${id}`)
  const [amount, setAmount] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!a) return <LoadState error={error} retry={reload} />
  if (a.productType !== 'checking' || a.status !== 'active') return <div className="state">입금할 수 있는 저축예금이 아니에요.</div>
  const n = Number(amount || 0)

  async function submit() {
    setBusy(true); setErr(null)
    try {
      await callJson('POST', `/api/accounts/${a!.accountId}/deposit`, { amount: n })
      nav(`/accounts/${a!.accountId}`, { replace: true, state: { flash: `${won(n)}을 입금했어요.` } })
    } catch (x) { setErr(errMsg(x)); setConfirm(false) } finally { setBusy(false) }
  }

  return (
    <section className="auth-page">
      <h2 className="auth-title">{accountName(a)}에 입금</h2>
      <p className="auth-notice">ATM 입금(시연용) · 1회 {won(LIMIT)}까지 입금할 수 있어요.</p>
      {!confirm ? (
        <>
          <AmountField value={amount} onChange={setAmount} max={LIMIT} hint={`현재 잔액 ${won(a.balance)}`} />
          {err && <p className="auth-err" role="alert">{err}</p>}
          <div className="auth-actions"><button type="button" className="primary" disabled={n < 1} onClick={() => setConfirm(true)}>다음</button></div>
        </>
      ) : (
        <>
          <dl className="auth-summary">
            <div><dt>입금 계좌</dt><dd>{a.bankName} {a.accountMasked}</dd></div>
            <div><dt>입금액</dt><dd>{won(n)}</dd></div>
            <div><dt>입금 후 잔액</dt><dd>{won(a.balance + n)}</dd></div>
          </dl>
          <div className="auth-actions">
            <button type="button" className="ghost" onClick={() => setConfirm(false)}>수정</button>
            <button type="button" className="primary" disabled={busy} onClick={() => void submit()}>입금하기</button>
          </div>
        </>
      )}
    </section>
  )
}
