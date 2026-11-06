import { useEffect, useState } from 'react'
import { Navigate, Outlet, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { won } from '../../format'
import { callJson } from '../../lib/http'
import { accountName, errCode, errMsg, useLoad, type Account } from './api'
import { AmountField, LoadState, PinDialog, Steps } from './parts'

type Target = { accountNo: string | null; accountId: number | null; name: string; masked: string }
type Draft = { from: Account | null; to: Target | null; amount: string; memo: string; result: Done | null }
type Done = { fromAccountMasked: string; toAccountMasked: string; toOwnerName: string; amount: number; memo: string | null; balance: number }
type Ctx = { draft: Draft; set: (p: Partial<Draft>) => void; accounts: Account[]; reload: () => void }
type Recent = { accountNo: string; accountMasked: string; ownerName: string; isMine: boolean }
type Fav = { id: number; accountNo: string; accountMasked: string; displayName: string | null }

const EMPTY: Draft = { from: null, to: null, amount: '', memo: '', result: null }
const BANKS = ['AIM Bank', '우리은행', '국민은행', '신한은행', '하나은행', '카카오뱅크']

/** A-08~A-11 이체 흐름. 네 화면이 입력 상태를 함께 쓰도록 부모 라우트가 상태를 들고 있다. */
export default function TransferFlow() {
  const { data, error, reload } = useLoad<{ items: Account[] }>('/api/accounts')
  const [draft, setDraft] = useState<Draft>(EMPTY)
  if (!data) return <LoadState error={error} retry={reload} />
  const accounts = data.items.filter((a) => a.productType === 'checking')
  return <Outlet context={{ draft, set: (p: Partial<Draft>) => setDraft((d) => ({ ...d, ...p })), accounts, reload } satisfies Ctx} />
}

const useFlow = () => useOutletContext<Ctx>()

/** A-08 이체 1단계: 출금 계좌, 받는 계좌(내 계좌 / 계좌번호 입력), 최근·자주 쓰는 계좌. */
export function TransferStep1() {
  const { draft, set, accounts } = useFlow()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [tab, setTab] = useState<'mine' | 'input'>('input')
  const [bank, setBank] = useState(BANKS[0])
  const [no, setNo] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [found, setFound] = useState<Target | null>(null)
  const recent = useLoad<{ items: Recent[] }>('/api/transfers/recent')
  const favs = useLoad<{ items: Fav[] }>('/api/favorites')

  useEffect(() => { // 출금 계좌 기본값: ?from= → 대표계좌 → 첫 계좌
    if (draft.from) return
    const want = Number(params.get('from'))
    set({ from: accounts.find((a) => a.accountId === want) ?? accounts.find((a) => a.isPrimary) ?? accounts[0] ?? null })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function lookup(accountNo: string) {
    setErr(null); setFound(null)
    try {
      const r = await callJson<{ ownerName: string; accountMasked: string }>('GET', `/api/transfers/recipient?accountNo=${encodeURIComponent(accountNo)}`)
      setFound({ accountNo, accountId: null, name: r.ownerName, masked: r.accountMasked })
    } catch (x) { setErr(errMsg(x)) }
  }
  const pick = (accountNo: string) => { setTab('input'); setBank(BANKS[0]); setNo(accountNo); void lookup(accountNo) }
  const other = bank !== BANKS[0]
  const mine = accounts.filter((a) => a.accountId !== draft.from?.accountId)

  async function addFavorite() {
    if (!found?.accountNo) return
    try { await callJson('POST', '/api/favorites', { accountNo: found.accountNo }); favs.reload() } catch (x) { setErr(errMsg(x)) }
  }

  return (
    <section className="auth-page">
      <Steps now={1} total={4} />
      <h2 className="auth-title">어디로 보낼까요?</h2>
      {accounts.length === 0 ? <p className="auth-err">이체할 저축예금이 없어요.</p> : (
        <>
          <label className="auth-field">출금 계좌
            <select className="ac-select" value={draft.from?.accountId ?? ''} onChange={(e) => set({ from: accounts.find((a) => a.accountId === Number(e.target.value)) ?? null, to: null })}>
              {accounts.map((a) => <option key={a.accountId} value={a.accountId}>{accountName(a)} {a.accountMasked} · {won(a.balance)}</option>)}
            </select>
          </label>
          <div className="chips" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'mine'} className={tab === 'mine' ? 'chip on' : 'chip'} onClick={() => setTab('mine')}>내 계좌</button>
            <button type="button" role="tab" aria-selected={tab === 'input'} className={tab === 'input' ? 'chip on' : 'chip'} onClick={() => setTab('input')}>계좌번호 입력</button>
          </div>
          {tab === 'mine' && (
            <ul className="ac-pick">
              {mine.length === 0 && <li className="state">다른 내 저축예금이 없어요.</li>}
              {mine.map((a) => (
                <li key={a.accountId}><button type="button" className={draft.to?.accountId === a.accountId ? 'on' : ''}
                  onClick={() => set({ to: { accountNo: null, accountId: a.accountId, name: accountName(a), masked: a.accountMasked } })}>
                  <strong>{accountName(a)}</strong><small>{a.accountMasked}</small></button></li>
              ))}
            </ul>
          )}
          {tab === 'input' && (
            <div className="auth-form">
              <label className="auth-field">은행
                <select className="ac-select" value={bank} onChange={(e) => { setBank(e.target.value); setFound(null); setErr(null) }}>{BANKS.map((b) => <option key={b}>{b}</option>)}</select>
              </label>
              {other ? <p className="auth-notice" role="status">타행 이체는 준비 중입니다.</p> : (
                <>
                  <label className="auth-field">계좌번호
                    <span className="ac-inline-form">
                      <input value={no} inputMode="numeric" placeholder="1002-123-456789" onChange={(e) => { setNo(e.target.value); setFound(null) }} />
                      <button type="button" disabled={!no.trim()} onClick={() => void lookup(no.trim())}>확인</button>
                    </span>
                  </label>
                  {found && (
                    <p className="auth-notice" role="status">예금주 <b>{found.name}</b> · {found.masked}
                      {!favs.data?.items.some((f) => f.accountNo === found.accountNo) && <> <button type="button" className="ac-inline" onClick={() => void addFavorite()}>★ 자주 쓰는 계좌 등록</button></>}</p>
                  )}
                </>
              )}
              {err && <p className="auth-err" role="alert">{err}</p>}
              <div className="ac-lists">
                <h4>최근 이체</h4>
                {recent.data?.items.length === 0 && <p className="small">최근 이체한 계좌가 없어요.</p>}
                <ul className="ac-pick">{recent.data?.items.filter((r) => r.accountMasked !== draft.from?.accountMasked).map((r) => <li key={r.accountNo}><button type="button" onClick={() => pick(r.accountNo)}><strong>{r.ownerName}{r.isMine && ' (내 계좌)'}</strong><small>{r.accountMasked}</small></button></li>)}</ul>
                <h4>자주 쓰는 계좌</h4>
                {favs.data?.items.length === 0 && <p className="small">등록한 계좌가 없어요.</p>}
                <ul className="ac-pick">{favs.data?.items.map((f) => (
                  <li key={f.id} className="ac-fav">
                    <button type="button" onClick={() => pick(f.accountNo)}><strong>{f.displayName ?? f.accountMasked}</strong><small>{f.accountMasked}</small></button>
                    <button type="button" className="ac-x" aria-label={`${f.displayName ?? f.accountMasked} 삭제`} onClick={() => void callJson('DELETE', `/api/favorites/${f.id}`).then(favs.reload)}>✕</button>
                  </li>))}</ul>
              </div>
            </div>
          )}
          <div className="auth-actions">
            <button type="button" className="primary" disabled={!draft.from || (tab === 'mine' ? !draft.to?.accountId : !found || other)}
              onClick={() => { if (tab === 'input' && found) set({ to: found }); nav('/transfer/amount') }}>다음</button>
          </div>
        </>
      )}
    </section>
  )
}

/** A-09 이체 2단계: 예금주 확인, 금액(한글 금액 병기), 잔액, 메모. 잔액을 넘으면 이 단계에 머문다(AF-01). */
export function TransferStep2() {
  const { draft, set } = useFlow()
  const nav = useNavigate()
  if (!draft.from || !draft.to) return <Navigate to="/transfer" replace />
  const n = Number(draft.amount || 0)
  const over = n > draft.from.balance
  return (
    <section className="auth-page">
      <Steps now={2} total={4} />
      <h2 className="auth-title">{draft.to.name}님께 얼마를 보낼까요?</h2>
      <p className="auth-sub">{draft.to.masked} · 출금 가능 {won(draft.from.balance)}</p>
      <AmountField value={draft.amount} onChange={(v) => set({ amount: v })} max={5_000_000}
        hint={over ? <b className="ac-warn">잔액이 부족합니다.</b> : '1회 500만원, 1일 1,000만원까지'} />
      <label className="auth-field">메모 (선택)<input value={draft.memo} maxLength={50} onChange={(e) => set({ memo: e.target.value })} /></label>
      <div className="auth-actions">
        <button type="button" className="ghost" onClick={() => nav('/transfer')}>이전</button>
        <button type="button" className="primary" disabled={n < 1 || over} onClick={() => nav('/transfer/confirm')}>다음</button>
      </div>
    </section>
  )
}

/** A-10 이체 확인: "이체하기" 때 서버가 간편비밀번호 확인(5분)을 요구하면 S-08 팝업을 띄우고 통과 뒤 다시 보낸다. */
export function TransferStep3() {
  const { draft, set } = useFlow()
  const nav = useNavigate()
  const [err, setErr] = useState<string | null>(null)
  const [pin, setPin] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!draft.from || !draft.to || !draft.amount) return <Navigate to="/transfer" replace />
  const { from, to } = draft
  const n = Number(draft.amount)

  async function send() {
    setBusy(true); setErr(null); setPin(false)
    try {
      const r = await callJson<Done>('POST', '/api/transfers', {
        fromAccountId: from!.accountId, amount: n, memo: draft.memo.trim() || null,
        ...(to!.accountId ? { toAccountId: to!.accountId } : { toAccountNo: to!.accountNo }),
      })
      set({ result: r })
      nav('/transfer/done', { replace: true })
    } catch (x) {
      if (errCode(x) === 'PIN_VERIFICATION_REQUIRED') setPin(true)
      else setErr(errMsg(x))
    } finally { setBusy(false) }
  }

  return (
    <section className="auth-page">
      <Steps now={3} total={4} />
      <h2 className="auth-title">이체 정보를 확인해 주세요</h2>
      <dl className="auth-summary">
        <div><dt>출금 계좌</dt><dd>{accountName(from)} {from.accountMasked}</dd></div>
        <div><dt>받는 분</dt><dd>{to.name} {to.masked}</dd></div>
        <div><dt>이체 금액</dt><dd>{won(n)}</dd></div>
        <div><dt>이체 후 잔액</dt><dd>{won(from.balance - n)}</dd></div>
        {draft.memo.trim() && <div><dt>메모</dt><dd>{draft.memo.trim()}</dd></div>}
      </dl>
      {err && <p className="auth-err" role="alert">{err}</p>}
      <div className="auth-actions">
        <button type="button" className="ghost" onClick={() => nav('/transfer/amount')}>금액 수정</button>
        <button type="button" className="primary" disabled={busy} onClick={() => void send()}>이체하기</button>
      </div>
      {pin && <PinDialog desc={`${to.name}님께 ${won(n)} 이체`} onVerified={() => void send()} onCancel={() => setPin(false)} />}
    </section>
  )
}

/** A-11 이체 완료. */
export function TransferDone() {
  const { draft, set, reload } = useFlow()
  const nav = useNavigate()
  const r = draft.result
  if (!r) return <Navigate to="/transfer" replace />
  return (
    <section className="auth-page center">
      <Steps now={4} total={4} />
      <h2 className="auth-title">{r.toOwnerName}님께 {won(r.amount)}을 보냈어요</h2>
      <dl className="auth-summary">
        <div><dt>출금 계좌</dt><dd>{r.fromAccountMasked}</dd></div>
        <div><dt>받는 계좌</dt><dd>{r.toAccountMasked}</dd></div>
        <div><dt>출금 후 잔액</dt><dd>{won(r.balance)}</dd></div>
        {r.memo && <div><dt>메모</dt><dd>{r.memo}</dd></div>}
      </dl>
      <div className="auth-actions">
        <button type="button" className="ghost" onClick={() => { reload(); set(EMPTY); nav('/transfer', { replace: true }) }}>한 번 더 이체</button>
        <button type="button" className="primary" onClick={() => nav('/accounts', { replace: true })}>확인</button>
      </div>
    </section>
  )
}
