import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { dDay, won } from '../../format'
import { callJson } from '../../lib/http'
import { accountName, errCode, errMsg, TYPE_LABEL, useLoad, type Account, type AccountDetail, type ClosePreview } from './api'
import { LoadState, PinDialog } from './parts'

/** A-12 해지: 저축예금은 잔액을 받을 계좌 선택, 예적금은 원금·경과일·적용 금리·해지 예상 이자(중도/만기 구분). 예적금은 해지 직전 S-08. */
export default function Close() {
  const id = useParams().id
  const detail = useLoad<AccountDetail>(`/api/accounts/${id}`)
  const preview = useLoad<ClosePreview>(`/api/accounts/${id}/close-preview`)
  const list = useLoad<{ items: Account[] }>('/api/accounts')
  const retry = () => { detail.reload(); preview.reload(); list.reload() }
  if (!detail.data || !preview.data || !list.data) return <LoadState error={detail.error ?? preview.error ?? list.error} retry={retry} />
  return <CloseForm a={detail.data} p={preview.data} others={list.data.items.filter((x) => x.productType === 'checking' && x.accountId !== detail.data!.accountId)} />
}

function CloseForm({ a, p, others }: { a: AccountDetail; p: ClosePreview; others: Account[] }) {
  const nav = useNavigate()
  const isCheck = p.productType === 'checking'
  const first = !isCheck ? p.receivingAccountId : others.find((o) => o.isPrimary)?.accountId ?? others[0]?.accountId
  const [recv, setRecv] = useState(String(first ?? ''))
  const [ok, setOk] = useState(false)
  const [pin, setPin] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const needTarget = isCheck ? p.balance > 0 : true
  const blocked = isCheck && p.blocker
  const noTarget = needTarget && !recv

  async function close() {
    setBusy(true); setErr(null); setPin(false)
    try {
      await callJson('POST', `/api/accounts/${a.accountId}/close`, { receivingAccountId: needTarget ? Number(recv) : null })
      nav('/accounts', { replace: true, state: { flash: `${accountName(a)} 계좌를 해지했어요.` } })
    } catch (x) {
      if (errCode(x) === 'PIN_VERIFICATION_REQUIRED') setPin(true)
      else setErr(errMsg(x))
    } finally { setBusy(false) }
  }

  return (
    <section className="auth-page">
      <h2 className="auth-title">{TYPE_LABEL[a.productType]} 해지</h2>
      <dl className="auth-summary">
        <div><dt>계좌</dt><dd>{accountName(a)} {a.accountMasked}</dd></div>
        {p.productType === 'checking' ? (
          <div><dt>잔액</dt><dd>{won(p.balance)}</dd></div>
        ) : (
          <>
            <div><dt>원금</dt><dd>{won(p.principal)}</dd></div>
            <div><dt>경과일</dt><dd>{p.elapsedDays}일 (만기 {p.maturityDate.replace(/-/g, '.')}{dDay(p.maturityDate) > 0 ? `, D-${dDay(p.maturityDate)}` : ''})</dd></div>
            <div><dt>{p.kind === 'matured' ? '만기 이자 (약정 금리)' : '중도해지 이자'}</dt><dd>연 {p.appliedRate.toFixed(1)}% · {won(p.interest)}</dd></div>
            <div><dt>받을 금액 (세전)</dt><dd><b>{won(p.total)}</b></dd></div>
          </>
        )}
      </dl>
      {p.productType !== 'checking' && p.kind === 'early' && <p className="auth-notice">중도 해지 시 약정 금리(연 {p.contractRate.toFixed(1)}%)보다 낮은 이자가 적용됩니다.</p>}
      {blocked && <p className="auth-err" role="alert">{blocked.message}</p>}
      {!blocked && needTarget && (
        others.length === 0 && isCheck
          ? <p className="auth-err" role="alert">받을 저축예금이 없어요. 잔액을 0원으로 만든 뒤 해지해 주세요.</p>
          : <label className="auth-field">{isCheck ? '잔액을 받을 저축예금' : '원금과 이자를 받을 저축예금'}
              <select className="ac-select" value={recv} onChange={(e) => setRecv(e.target.value)}>
                {others.map((o) => <option key={o.accountId} value={o.accountId}>{accountName(o)} {o.accountMasked} · {won(o.balance)}</option>)}
              </select>
            </label>
      )}
      {!blocked && (
        <>
          <label className="auth-check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />위 내용을 확인했으며 해지에 동의합니다</label>
          {err && <p className="auth-err" role="alert">{err}</p>}
        </>
      )}
      <div className="auth-actions">
        <button type="button" className="ghost" onClick={() => nav(-1)}>취소</button>
        <button type="button" className="primary" disabled={!!blocked || !ok || noTarget || busy} onClick={() => void close()}>해지하기</button>
      </div>
      {pin && <PinDialog desc={`${TYPE_LABEL[a.productType]} 해지`} onVerified={() => void close()} onCancel={() => setPin(false)} />}
    </section>
  )
}
