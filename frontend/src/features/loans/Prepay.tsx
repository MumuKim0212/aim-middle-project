import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { won } from '../../format'
import { callJson } from '../../lib/http'
import { accountName, errCode, errMsg, useLoad, type Account } from '../accounts/api'
import { AmountField, PinDialog } from '../accounts/parts'
import { prepay, type Loan, type PrepayQuote } from './api'
import { LoanLoad } from './parts'

/** 중도상환: 금액·출금 계좌 입력 → 견적(수수료·이자·총액) 확인 → 간편비밀번호 재확인 뒤 상환. */
export default function LoanPrepay() {
  const no = useParams().no
  const detail = useLoad<Loan>(`/api/loans/${no}`)
  const list = useLoad<{ items: Account[] }>('/api/accounts')
  const retry = () => { detail.reload(); list.reload() }
  if (!detail.data || !list.data) return <LoanLoad error={detail.error ?? list.error} retry={retry} />
  if (detail.data.status !== 'ACTIVE' || detail.data.balance < 1) return <div className="state">중도상환할 수 있는 대출이 아니에요.</div>
  return <PrepayForm l={detail.data} accounts={list.data.items.filter((a) => a.productType === 'checking' && a.status === 'active')} />
}

function PrepayForm({ l, accounts }: { l: Loan; accounts: Account[] }) {
  const nav = useNavigate()
  const first = accounts.find((a) => a.accountId === l.debitAccountId) ?? accounts.find((a) => a.isPrimary) ?? accounts[0]
  const [amount, setAmount] = useState('')
  const [from, setFrom] = useState(String(first?.accountId ?? ''))
  const [quote, setQuote] = useState<PrepayQuote | null>(null)
  const [key] = useState(() => crypto.randomUUID()) // 실패하면 서버가 되돌리므로 같은 키로 다시 보내도 된다
  const [pin, setPin] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const n = Number(amount || 0)
  const account = accounts.find((a) => String(a.accountId) === from)

  async function getQuote() {
    setBusy(true); setErr(null)
    try { setQuote(await callJson<PrepayQuote>('GET', `/api/loans/${l.contractNo}/prepay-quote?principal=${n}`)) }
    catch (x) { setErr(errMsg(x)) } finally { setBusy(false) }
  }

  async function submit() {
    setBusy(true); setErr(null); setPin(false)
    try {
      const r = await prepay(l.contractNo, { principal: n, accountId: Number(from) }, key)
      nav(`/loans/${l.contractNo}`, { replace: true, state: { flash: `${won(r.principal)}을 중도상환했어요. 남은 잔액은 ${won(r.balance)}이에요.` } })
    } catch (x) {
      if (errCode(x) === 'PIN_VERIFICATION_REQUIRED') setPin(true)
      else { setErr(errMsg(x)); setQuote(null) }
    } finally { setBusy(false) }
  }

  if (accounts.length === 0) return <div className="state">출금할 저축예금이 없어요.</div>
  return (
    <section className="auth-page">
      <h2 className="auth-title">중도상환</h2>
      {!quote ? (
        <>
          <AmountField value={amount} onChange={setAmount} max={l.balance} hint={`대출 잔액 ${won(l.balance)}`} />
          <label className="auth-field">출금 계좌
            <select className="ac-select" value={from} onChange={(e) => setFrom(e.target.value)}>
              {accounts.map((a) => <option key={a.accountId} value={a.accountId}>{accountName(a)} {a.accountMasked} · {won(a.balance)}</option>)}
            </select>
          </label>
          {err && <p className="auth-err" role="alert">{err}</p>}
          <div className="auth-actions"><button type="button" className="primary" disabled={n < 1 || busy} onClick={() => void getQuote()}>다음</button></div>
        </>
      ) : (
        <>
          <dl className="auth-summary">
            <div><dt>출금 계좌</dt><dd>{account && `${accountName(account)} ${account.accountMasked}`}</dd></div>
            <div><dt>상환 원금</dt><dd>{won(quote.principal)}</dd></div>
            <div><dt>중도상환 수수료</dt><dd>{quote.feeFree ? '면제' : won(quote.fee)}</dd></div>
            <div><dt>이자</dt><dd>{won(quote.interest)}</dd></div>
            <div><dt>총 출금액</dt><dd><b>{won(quote.total)}</b></dd></div>
            <div><dt>상환 후 잔액</dt><dd>{won(l.balance - quote.principal)}</dd></div>
          </dl>
          {err && <p className="auth-err" role="alert">{err}</p>}
          <div className="auth-actions">
            <button type="button" className="ghost" onClick={() => setQuote(null)}>수정</button>
            <button type="button" className="primary" disabled={busy} onClick={() => void submit()}>중도상환하기</button>
          </div>
        </>
      )}
      {pin && <PinDialog desc={`대출 중도상환 ${won(quote?.total ?? 0)}`} onVerified={() => void submit()} onCancel={() => setPin(false)} />}
    </section>
  )
}
