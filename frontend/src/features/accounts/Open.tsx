import { useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { won } from '../../format'
import { callJson } from '../../lib/http'
import { accountName, errMsg, TYPE_LABEL, useLoad, type AccountDetail, type Account, type Product, type ProductType } from './api'
import { AmountField, LoadState, Steps } from './parts'

const TYPES: ProductType[] = ['checking', 'deposit', 'savings']

/** A-03 계좌 개설: 조건 확인 → 상품별 설정 → 약관 동의 → 완료. 모든 조건은 서버가 다시 검증한다. */
export default function Open() {
  const { type } = useParams()
  const products = useLoad<{ items: Product[] }>('/api/products')
  const accounts = useLoad<{ items: Account[] }>('/api/accounts')
  if (!TYPES.includes(type as ProductType)) return <Navigate to="/products" replace />
  if (!products.data || !accounts.data) return <LoadState error={products.error ?? accounts.error} retry={() => { products.reload(); accounts.reload() }} />
  const product = products.data.items.find((p) => p.type === type)!
  return <OpenForm product={product} mine={accounts.data.items} />
}

/** 조건을 못 채우면 사유(AF-07·08). 서버 검증과 같은 규칙이라 화면에서 먼저 막아 보여 준다. */
function blocker(p: Product, mine: Account[]): { text: string; link?: { to: string; label: string } } | null {
  const same = mine.filter((a) => a.productType === p.type)
  if (p.maxPerUser !== null && same.length >= p.maxPerUser)
    return { text: p.type === 'savings' ? '정기적금은 1인 1계좌만 가입할 수 있습니다.' : `저축예금은 최대 ${p.maxPerUser}개까지 가입할 수 있습니다.` }
  if (p.requiresChecking && !mine.some((a) => a.productType === 'checking'))
    return { text: '저축예금을 먼저 개설해 주세요.', link: { to: '/products/checking/open', label: '저축예금 가입하기' } }
  return null
}

function OpenForm({ product: p, mine }: { product: Product; mine: Account[] }) {
  const nav = useNavigate()
  const checking = mine.filter((a) => a.productType === 'checking')
  const [step, setStep] = useState(1)
  const [alias, setAlias] = useState('')
  const [primary, setPrimary] = useState(false)
  const [amount, setAmount] = useState('')
  const [months, setMonths] = useState('12')
  const [day, setDay] = useState('25')
  const [autoPay, setAutoPay] = useState(true)
  const [linked, setLinked] = useState(String(checking.find((a) => a.isPrimary)?.accountId ?? checking[0]?.accountId ?? ''))
  const [agreed, setAgreed] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const block = blocker(p, mine)
  const isCheck = p.type === 'checking'
  const need = Number(amount || 0)
  const source = checking.find((a) => String(a.accountId) === linked)
  const short = !isCheck && source !== undefined && source.balance < need
  const monthsNum = Number(months)
  const settingsOk = isCheck || (need >= (p.minAmount ?? 0) && need <= (p.maxAmount ?? Infinity) && !!source && !short
    && (p.type === 'savings' || (monthsNum >= (p.minMonths ?? 1) && monthsNum <= (p.maxMonths ?? 36) && Number.isInteger(monthsNum))))

  async function submit() {
    setBusy(true); setErr(null)
    try {
      const acc = await callJson<AccountDetail>('POST', '/api/accounts', {
        productType: p.type, agreed, alias: isCheck ? alias.trim() || null : null, isPrimary: primary,
        ...(p.type === 'deposit' ? { amount: need, termMonths: monthsNum } : {}),
        ...(p.type === 'savings' ? { monthlyAmount: need, paymentDay: Number(day), autoPay } : {}),
        ...(isCheck ? {} : { linkedAccountId: Number(linked) }),
      })
      nav(`/accounts/${acc.accountId}`, { replace: true, state: { flash: `${TYPE_LABEL[p.type]} 계좌를 만들었어요.` } })
    } catch (x) { setErr(errMsg(x)) } finally { setBusy(false) }
  }

  return (
    <section className="auth-page">
      <Steps now={step} total={3} />
      <h2 className="auth-title">{p.name} 가입</h2>
      {step === 1 && (
        <>
          <dl className="auth-summary">
            <div><dt>연 금리</dt><dd>{p.rate.toFixed(1)}%{isCheck && ' (표시만)'}</dd></div>
            {p.earlyCloseRate !== null && <div><dt>중도해지 금리</dt><dd>연 {p.earlyCloseRate.toFixed(1)}%</dd></div>}
            {!isCheck && <div><dt>{p.type === 'savings' ? '월 납입액' : '가입 금액'}</dt><dd>{won(p.minAmount ?? 0)} ~ {won(p.maxAmount ?? 0)}</dd></div>}
            {!isCheck && <div><dt>가입 기간</dt><dd>{p.minMonths === p.maxMonths ? `${p.maxMonths}개월 고정` : `${p.minMonths}~${p.maxMonths}개월`}</dd></div>}
            <div><dt>가입 조건</dt><dd>{p.requiresChecking ? '저축예금 보유' : '로그인한 누구나'}{p.maxPerUser ? ` · 1인 최대 ${p.maxPerUser}개` : ''}</dd></div>
          </dl>
          {block && <p className="auth-err" role="alert">{block.text}{block.link && <> <Link to={block.link.to} className="ac-inline">{block.link.label}</Link></>}</p>}
          <div className="auth-actions">
            <button type="button" className="ghost" onClick={() => nav('/products')}>취소</button>
            <button type="button" className="primary" disabled={!!block} onClick={() => setStep(2)}>다음</button>
          </div>
        </>
      )}
      {step === 2 && (
        <div className="auth-form">
          {isCheck && (
            <>
              <label className="auth-field">별명 (선택)<input value={alias} maxLength={20} onChange={(e) => setAlias(e.target.value)} placeholder="예: 생활비" /></label>
              <label className="auth-check"><input type="checkbox" checked={primary || checking.length === 0} disabled={checking.length === 0} onChange={(e) => setPrimary(e.target.checked)} />대표계좌로 설정{checking.length === 0 && ' (첫 계좌는 자동으로 대표)'}</label>
            </>
          )}
          {!isCheck && (
            <>
              <div className="auth-field">{p.type === 'savings' ? '월 납입액' : '예치 금액'}
                <AmountField value={amount} onChange={setAmount} max={p.maxAmount ?? undefined}
                  hint={`${won(p.minAmount ?? 0)} 이상 ${won(p.maxAmount ?? 0)} 이하`} />
              </div>
              {p.type === 'deposit' && <label className="auth-field">기간 (개월, {p.minMonths}~{p.maxMonths})<input type="number" inputMode="numeric" min={p.minMonths ?? 1} max={p.maxMonths ?? 36} value={months} onChange={(e) => setMonths(e.target.value)} /></label>}
              {p.type === 'savings' && (
                <>
                  <label className="auth-field">납입일 (매월)<select className="ac-select" value={day} onChange={(e) => setDay(e.target.value)}>{Array.from({ length: 28 }, (_, i) => <option key={i} value={i + 1}>{i + 1}일</option>)}</select></label>
                  <label className="auth-check"><input type="checkbox" checked={autoPay} onChange={(e) => setAutoPay(e.target.checked)} />매월 납입일에 자동이체 (기간 12개월 고정)</label>
                </>
              )}
              <label className="auth-field">출금 계좌 (납입·만기 입금 계좌)
                <select className="ac-select" value={linked} onChange={(e) => setLinked(e.target.value)}>
                  {checking.map((a) => <option key={a.accountId} value={a.accountId}>{accountName(a)} {a.accountMasked} · {won(a.balance)}</option>)}
                </select>
              </label>
              {short && <p className="auth-err" role="alert">출금 계좌 잔액이 부족합니다.</p>}
            </>
          )}
          <div className="auth-actions">
            <button type="button" className="ghost" onClick={() => setStep(1)}>이전</button>
            <button type="button" className="primary" disabled={!settingsOk} onClick={() => setStep(3)}>다음</button>
          </div>
        </div>
      )}
      {step === 3 && (
        <div className="auth-form">
          <dl className="auth-summary">
            <div><dt>상품</dt><dd>{p.name}</dd></div>
            {isCheck && <div><dt>별명</dt><dd>{alias.trim() || '—'}</dd></div>}
            {p.type !== 'checking' && <div><dt>{p.type === 'savings' ? '월 납입액' : '예치 금액'}</dt><dd>{won(need)}</dd></div>}
            {p.type === 'deposit' && <div><dt>기간</dt><dd>{monthsNum}개월</dd></div>}
            {p.type === 'savings' && <div><dt>납입일 · 자동이체</dt><dd>매월 {day}일 · {autoPay ? '켜짐' : '꺼짐'}</dd></div>}
            {source && <div><dt>출금 계좌</dt><dd>{accountName(source)} {source.accountMasked}</dd></div>}
          </dl>
          <label className="auth-check"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
            <span>상품 설명과 이용 약관에 동의합니다{p.type === 'savings' && autoPay && <><br />매월 납입일에 지정 저축예금에서 자동 출금됩니다.</>}</span></label>
          {err && <p className="auth-err" role="alert">{err}</p>}
          <div className="auth-actions">
            <button type="button" className="ghost" onClick={() => setStep(2)}>이전</button>
            <button type="button" className="primary" disabled={!agreed || busy} onClick={() => void submit()}>개설하기</button>
          </div>
        </div>
      )}
    </section>
  )
}
