import { useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { dDay, won } from '../../format'
import { callJson } from '../../lib/http'
import { errCode, errMsg, useLoad } from '../accounts/api'
import { PinDialog } from '../accounts/parts'
import { STATUS_LABEL, type Loan, type LoanSummary, type WithdrawResult } from './api'
import { LoanLoad } from './parts'

const WITHDRAW_DAYS = 14 // 서버(loan/config.py WITHDRAW_DAYS)와 같다
// shortcut: 철회 가능 여부를 API 가 주지 않아 상태·실행일로 계산한다, 서버가 가능 여부 필드를 내려 주면 그 값을 쓴다.
const canWithdraw = (l: Loan) => l.status === 'ACTIVE' && dDay(l.startDate) + WITHDRAW_DAYS >= 0

/** 대출 상세: 계약 내용과 상환 일정·중도상환 이동, 청약철회(실행일 14일 안, 간편비밀번호 재확인). */
export default function LoanDetail() {
  const no = useParams().no
  const detail = useLoad<Loan>(`/api/loans/${no}`)
  const list = useLoad<{ items: LoanSummary[] }>('/api/loans') // 상세 응답에는 상품 이름이 없어 목록에서 찾는다
  const [done, setDone] = useState<string | null>(null) // 다시 불러오면 화면이 새로 그려져서 철회 결과 문구는 여기에 둔다
  const navFlash = (useLocation().state as { flash?: string } | null)?.flash
  const flash = done ?? navFlash
  if (!detail.data || !list.data) return <LoanLoad error={detail.error ?? list.error} retry={() => { detail.reload(); list.reload() }} />
  return <DetailView l={detail.data} name={list.data.items.find((x) => x.contractNo === detail.data!.contractNo)?.productName ?? '대출'} flash={flash} onChanged={(m) => { setDone(m); detail.reload(); list.reload() }} />
}

function DetailView({ l, name, flash, onChanged }: { l: Loan; name: string; flash?: string; onChanged: (msg: string) => void }) {
  const [ok, setOk] = useState(false)
  const [pin, setPin] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(flash ?? null)
  const [busy, setBusy] = useState(false)
  const active = l.status === 'ACTIVE'

  async function withdraw() {
    setBusy(true); setErr(null); setMsg(null); setPin(false)
    try {
      const r = await callJson<WithdrawResult>('POST', `/api/loans/${l.contractNo}/withdraw`)
      if (r.accepted) onChanged(`청약을 철회했어요. 반환 금액은 ${won(r.refund)}이에요.`)
      else setErr(`청약철회 기한(${r.deadline.replace(/-/g, '.')})이 지나 철회할 수 없어요.`)
    } catch (x) {
      if (errCode(x) === 'PIN_VERIFICATION_REQUIRED') setPin(true)
      else setErr(errMsg(x))
    } finally { setBusy(false) }
  }

  return (
    <section className="ac-page">
      {msg && <p className="auth-flash" role="status">{msg}</p>}
      <h2 className="auth-title">{name}{!active && <span className="tag">{STATUS_LABEL[l.status]}</span>}</h2>
      <dl className="auth-summary">
        <div><dt>대출 계좌</dt><dd>{l.accountMasked}</dd></div>
        <div><dt>대출 잔액</dt><dd><b>{won(l.balance)}</b></dd></div>
        <div><dt>대출 원금</dt><dd>{won(l.principal)}</dd></div>
        <div><dt>금리</dt><dd>연 {l.rate}%</dd></div>
        <div><dt>대출 기간</dt><dd>{l.termMonths}개월</dd></div>
        <div><dt>상환 방식</dt><dd>{l.repayMethod}</dd></div>
        <div><dt>실행일</dt><dd>{l.startDate.replace(/-/g, '.')}</dd></div>
        {active && l.nextDueDate && <div><dt>다음 상환일</dt><dd>{l.nextDueDate.replace(/-/g, '.')}</dd></div>}
      </dl>
      <div className="ac-actions">
        <Link to={`/loans/${l.contractNo}/schedule`}>상환 일정</Link>
        {active && l.balance > 0 && <Link to={`/loans/${l.contractNo}/prepay`}>중도상환</Link>}
      </div>
      {canWithdraw(l) && (
        <>
          <p className="auth-notice">실행일부터 {WITHDRAW_DAYS}일 안에는 청약을 철회할 수 있어요. 대출금과 이자·부대비용을 되돌려 드려요.</p>
          <label className="auth-check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />청약철회에 동의합니다</label>
          <div className="auth-actions"><button type="button" className="ghost" disabled={!ok || busy} onClick={() => void withdraw()}>청약철회</button></div>
        </>
      )}
      {err && <p className="auth-err" role="alert">{err}</p>}
      {pin && <PinDialog desc={`${name} 청약철회`} onVerified={() => void withdraw()} onCancel={() => setPin(false)} />}
    </section>
  )
}
