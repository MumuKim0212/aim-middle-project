import { useEffect, useRef, useState, type ComponentType } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { koreanAmount } from '../../../format'
import { callJson } from '../../../lib/http'
import { errCode, useLoad } from '../../accounts/api'
import { Steps } from '../../accounts/parts'
import type { LoanProduct } from '../api'
import { LoanLoad } from '../parts'
import '../loans.css'
import { ENDED, SCENARIOS, STEP, readLast, readStash, stepFor, writeLast, writeStash, type AppState, type Stash } from './model'
import { Affiliation, Compare, Docs, Guarantee, PolicyCheck, Result, Review } from './StepsB'
import { Collateral, Contract, Done, Execute, Explain, Payoff, Pricing, Terms } from './StepsC'
import { Consent, Fetch, Precheck, Profile, Targets } from './StepsA'
import { Ctx, ErrBox, useRun, type FlowCtx } from './shared'

const VIEW: Record<string, ComponentType> = {
  precheck: Precheck, consent: Consent, fetch: Fetch, targets: Targets, profile: Profile, policycheck: PolicyCheck, guarantee: Guarantee,
  affiliation: Affiliation, docs: Docs, review: Review, result: Result, compare: Compare, terms: Terms, pricing: Pricing, explain: Explain,
  contract: Contract, collateral: Collateral, execute: Execute, payoff: Payoff, done: Done,
}
const apps = '/api/loans/applications'

/** 신청 시작: 상품 안내와 체험 고객 선택. 시작하면 서버가 단계 목록(flow)을 정해 주고 첫 단계로 간다. */
export function ApplyStart() {
  const productId = useParams().productId
  const nav = useNavigate()
  const products = useLoad<{ items: LoanProduct[] }>('/api/loans/products')
  const [scn, setScn] = useState('')
  const { busy, err, run } = useRun()
  if (!products.data) return <LoanLoad error={products.error} retry={products.reload} />
  const p = products.data.items.find((x) => x.productId === productId)
  if (!p) return <div className="state">상품을 찾을 수 없어요.</div>

  async function start() {
    const r = await run(() => callJson<AppState>('POST', apps, { productId: p!.productId, ...(scn ? { scenarioKey: scn } : {}) }))
    if (!r) return
    writeStash(r.applicationId, { scenario: scn || undefined, productId: r.productId, flow: r.flow })
    writeLast({ id: r.applicationId, name: p!.name })
    nav(`/loans/apply/${r.applicationId}/${r.flow[0]}`, { replace: true })
  }
  return (
    <section className="auth-page">
      <h2 className="auth-title">{p.name}</h2>
      <p className="auth-sub">{p.subtitle}</p>
      <dl className="auth-summary">
        <div><dt>대상</dt><dd>{p.targetDesc}</dd></div>
        <div><dt>대출 한도</dt><dd>{koreanAmount(p.minAmount)} ~ {koreanAmount(p.maxAmount)}</dd></div>
        <div><dt>금리 (예시)</dt><dd>연 {p.rateMin.toFixed(2)}% ~ {p.rateMax.toFixed(2)}%</dd></div>
        <div><dt>대출 기간</dt><dd>{p.termOptions.map((t) => (t % 12 === 0 ? `${t / 12}년` : `${t}개월`)).join(', ')}</dd></div>
        <div><dt>상환 방법</dt><dd>{p.repayOptions.join(', ')}</dd></div>
      </dl>
      <label className="auth-field">체험 고객 (선택)
        <select className="ac-select" value={scn} onChange={(e) => setScn(e.target.value)}>
          <option value="">직접 입력</option>
          {SCENARIOS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </label>
      <p className="small">가상 고객을 고르면 고객정보와 제출 서류가 자동으로 채워져요. 직접 입력해도 돼요.</p>
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void start()}>{p.businessType === 'REFI' ? '갈아타기 신청' : '대출 신청'}</button></div>
    </section>
  )
}

export function ApplyFlow() {
  const id = useParams().applicationId ?? ''
  return <Flow key={id} id={id} />
}

/** 신청 단계 틀: 서버의 신청 상태를 읽어 진행 표시와 단계 화면을 그리고, 상태가 어긋나면 지금 단계로 되돌린다. */
function Flow({ id }: { id: string }) {
  const step = useParams().step ?? ''
  const nav = useNavigate()
  const products = useLoad<{ items: LoanProduct[] }>('/api/loans/products')
  const [loaded, setLoaded] = useState<{ key: string; app: AppState } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tick, setTick] = useState(0)
  const [stash, setStash] = useState(() => readStash(id))
  const stashRef = useRef(stash)
  const closed = step === 'payoff' || step === 'done' // 실행이 끝나면 신청이 서버에서 사라진다(404)
  const key = `${id}/${step}`

  useEffect(() => {
    if (closed) return
    let alive = true
    setError(null)
    callJson<AppState>('GET', `${apps}/${id}`).then((app) => alive && setLoaded({ key, app })).catch((e) => alive && setError(e))
    return () => { alive = false }
  }, [id, key, closed, tick])

  const app = loaded?.key === key ? loaded.app : null
  const meta = app ?? loaded?.app ?? (stash.productId && stash.flow ? { productId: stash.productId, flow: stash.flow } : null)
  useEffect(() => { // 끝난 뒤의 화면(payoff·done)이 새로 열려도 알 수 있게 기억해 둔다
    if (loaded && stashRef.current.productId !== loaded.app.productId) patch({ productId: loaded.app.productId, flow: loaded.app.flow })
  }, [loaded]) // eslint-disable-line react-hooks/exhaustive-deps

  function patch(s: Partial<Stash>) {
    stashRef.current = { ...stashRef.current, ...s }
    writeStash(id, stashRef.current)
    setStash(stashRef.current)
  }

  if (!products.data) return <LoanLoad error={products.error} retry={products.reload} />
  if (error && !closed) {
    if (errCode(error) === 'LOAN_NOT_FOUND') {
      if (readLast()?.id === id) writeLast(null)
      return <div className="state">신청을 찾을 수 없어요. 만료되었다면 처음부터 다시 신청해 주세요.<br /><Link to="/loans" className="ac-retry">대출 상품 보기</Link></div>
    }
    return <LoanLoad error={error} retry={() => setTick((n) => n + 1)} />
  }
  if (!meta || (!closed && !app)) return <div className="state">불러오는 중…</div>
  const product = products.data.items.find((p) => p.productId === meta.productId)
  if (!product) return <div className="state">상품을 찾을 수 없어요.</div>
  const flow = meta.flow
  if (!closed && app && !flow.includes(step)) return <Navigate to={`/loans/apply/${id}/${stepFor(app.status, flow)}`} replace />
  if (app && ENDED[app.status] && !(app.status === 'REJECTED' && (step === 'result' || step === 'compare'))) {
    return (
      <section className="auth-page">
        <div className="ln-box ng"><b>{ENDED[app.status]}</b></div>
        <div className="auth-stack"><Link to="/loans" className="auth-btn">대출 상품 보기</Link></div>
      </section>
    )
  }

  const at = flow.indexOf(step)
  const ctx: FlowCtx = {
    id, step, product, products: products.data.items, flow, app, stash, patch,
    next: (state) => nav(`/loans/apply/${id}/${flow[at + 1]}`, { state, replace: step === 'execute' }),
    goStep: (s) => nav(`/loans/apply/${id}/${s}`),
    goCurrent: () => { // 상태가 어긋났을 때: 서버가 말하는 지금 단계로 간다
      callJson<AppState>('GET', `${apps}/${id}`).then((a) => nav(`/loans/apply/${id}/${stepFor(a.status, a.flow)}`, { replace: true })).catch(setError)
    },
  }
  const View = VIEW[step]
  const [title, sub] = STEP[step] ?? ['']
  return (
    <section className="auth-page">
      <Steps now={at + 1} total={flow.length} />
      <h2 className="auth-title">{title}</h2>
      {sub && <p className="auth-sub">{sub}</p>}
      <Ctx.Provider value={ctx}>{View ? <View key={step} /> : <div className="state">알 수 없는 단계예요.</div>}</Ctx.Provider>
    </section>
  )
}
