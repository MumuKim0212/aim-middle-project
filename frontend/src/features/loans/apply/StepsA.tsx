import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { won } from '../../../format'
import { callJson } from '../../../lib/http'
import { useLoad } from '../../accounts/api'
import { LoanLoad } from '../parts'
import { JOBS, OPTIONAL_CONSENTS, RATE_PREFS, REASON, type ExistingLoan, type ProfileResult } from './model'
import { ErrBox, ManField, Seg, pct, toMan, useFlow, useRun } from './shared'

const base = (id: string) => `/api/loans/applications/${id}`

/** 같은 담보 종류의 일반대출(정책·협약 자격이 안 될 때 갈아탈 곳). */
export function useFallback() {
  const { products, product } = useFlow()
  return products.find((p) => p.businessType === 'GENERAL' && p.collateralType === product.collateralType)
}

export function Ineligible({ title, codes }: { title: string; codes: string[] }) {
  const fb = useFallback()
  return (
    <>
      <div className="ln-box ng"><b>{title}</b><ul className="ln-reasons">{codes.map((c) => <li key={c}><code>{c}</code> {REASON[c]}</li>)}</ul></div>
      <div className="auth-stack">
        {fb && <Link to={`/loans/apply/${fb.productId}`} className="auth-btn">같은 목적의 일반대출로 전환</Link>}
        <Link to="/loans" className="auth-btn">처음으로</Link>
      </div>
    </>
  )
}

/** (정부) 입력값으로 하는 자격 사전 확인. */
export function Precheck() {
  const { id, next } = useFlow()
  const [f, setF] = useState({ homeless: true, married: false, income: '', assets: '' })
  const [res, setRes] = useState<{ name: string; ok: boolean; code: string | null }[] | null>(null)
  const { busy, err, run } = useRun()
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }))

  async function submit() {
    const r = await run(() => callJson<{ items: { name: string; ok: boolean; code: string | null }[] }>('POST', `${base(id)}/precheck`,
      { homeless: f.homeless, married: f.married, householdIncome: Number(f.income) * 10_000, netAssets: Number(f.assets) * 10_000 }))
    if (r) setRes(r.items)
  }

  if (res) {
    const failed = res.filter((r) => !r.ok)
    return (
      <>
        <ul className="ac-tx">
          {res.map((r) => <li key={r.name}><div><strong>{r.name}</strong>{r.code && <small>{REASON[r.code]}</small>}</div><span className={`tag ${r.ok ? 'ok' : 'ng'}`}>{r.ok ? '충족' : '미충족'}</span></li>)}
        </ul>
        {failed.length === 0 ? (
          <>
            <div className="ln-box ok">사전 확인 충족 — 참고 결과이며, 서류·행정정보 확인 후 확정돼요.</div>
            <div className="auth-actions"><button type="button" className="primary" onClick={() => next()}>자격 충족 · 다음</button></div>
          </>
        ) : <Ineligible title="정책 자격 미충족" codes={failed.map((r) => r.code!)} />}
      </>
    )
  }
  return (
    <div className="auth-form">
      <Seg label="무주택 여부 (세대원 전원)" value={f.homeless} onChange={(v) => set('homeless', v)} options={[[true, '무주택'], [false, '주택 소유']]} />
      <Seg label="혼인 여부" value={f.married} onChange={(v) => set('married', v)} options={[[false, '미혼'], [true, '기혼']]} />
      <ManField label={f.married ? '부부합산 연 소득' : '본인 연 소득'} value={f.income} onChange={(v) => set('income', v)} />
      <ManField label="세대 순자산" value={f.assets} onChange={(v) => set('assets', v)} />
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy || !f.income || !f.assets} onClick={() => void submit()}>확인</button></div>
    </div>
  )
}

/** 필수 동의 + 선택 동의. 자동 연동 동의는 이 단계에서만 받을 수 있다(서버가 뒤 단계에서는 동의를 다시 받지 않는다). */
export function Consent() {
  const { id, patch, next } = useFlow()
  const req = useLoad<{ required: { code: string; title: string }[] }>(`${base(id)}/consents`)
  const [on, setOn] = useState<Record<string, boolean>>({})
  const { busy, err, run } = useRun()
  if (!req.data) return <LoanLoad error={req.error} retry={req.reload} />
  const rows = [...req.data.required.map((c) => ({ ...c, must: true })), ...OPTIONAL_CONSENTS.map(([code, title]) => ({ code, title, must: false }))]
  const all = rows.every((r) => on[r.code])
  const ready = req.data.required.every((c) => on[c.code])

  async function submit() {
    const agreed = Object.fromEntries(Object.entries(on).filter(([, v]) => v))
    if (await run(() => callJson('POST', `${base(id)}/consents`, { agreed })) !== undefined) { patch({ agreed: Object.keys(agreed) }); next() }
  }

  return (
    <div className="auth-form">
      <div className="auth-terms">
        <label className="all"><input type="checkbox" checked={all} onChange={(e) => setOn(Object.fromEntries(rows.map((r) => [r.code, e.target.checked])))} /> 전체 동의 (선택 항목 포함)</label>
        {rows.map((r) => (
          <label key={r.code}><input type="checkbox" checked={!!on[r.code]} onChange={(e) => setOn((p) => ({ ...p, [r.code]: e.target.checked }))} /> {r.must ? <b>[필수]</b> : '[선택]'} {r.title}</label>
        ))}
      </div>
      {req.data.required.some((c) => c.code === 'SPOUSE_INQUIRY') && <p className="auth-notice">배우자 본인 동의가 필요한 항목이에요. 데모에서는 체크하면 동의로 처리해요.</p>}
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={!ready || busy} onClick={() => void submit()}>동의하고 다음</button></div>
    </div>
  )
}

function LoanRow({ l, right }: { l: ExistingLoan; right?: ReactNode }) {
  return (
    <div className="ln-loan">
      <div><strong>{l.institution}</strong><small>{l.kind} · 연 {l.rate}% · 실행 후 {l.since}개월 · 남은 {l.remain}개월</small><b>{won(l.balance)}</b></div>
      {right}
    </div>
  )
}

/** (대환) 마이데이터로 기존 대출 조회. */
export function Fetch() {
  const { id, stash, patch, next } = useFlow()
  const [items, setItems] = useState<ExistingLoan[] | null>(null)
  const { busy, err, run } = useRun()
  async function submit() {
    const r = await run(() => callJson<{ items: ExistingLoan[] }>('POST', `${base(id)}/existing`))
    if (r) { setItems(r.items); patch({ existing: r.items }) }
  }
  const shown = items ?? stash.existing
  return (
    <div className="auth-form">
      {shown ? (
        <>
          <p className="auth-notice">조회된 대출 {shown.length}건</p>
          <ul className="ln-list">{shown.map((l) => <li key={l.id}><LoanRow l={l} /></li>)}</ul>
          <div className="auth-actions"><button type="button" className="primary" onClick={() => next()}>조회 결과 확인</button></div>
        </>
      ) : (
        <>
          <ErrBox err={err} />
          <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void submit()}>{busy ? '조회하는 중…' : '기존 대출 조회'}</button></div>
        </>
      )}
    </div>
  )
}

/** (대환) 갈아탈 대출 고르기. 불가 대출은 고를 수 없다. */
export function Targets() {
  const { id, stash, patch, next } = useFlow()
  const nav = useNavigate()
  const list = stash.existing
  const [sel, setSel] = useState<number[]>([])
  const [none, setNone] = useState(false)
  const { busy, err, run } = useRun()
  const eligible = list?.some((l) => l.codes.length === 0) ?? true // 목록을 모르면 서버가 가능한 대출을 모두 고른다

  async function submit(indexes?: number[]) {
    const r = await run(() => callJson<{ items: ExistingLoan[] }>('POST', `${base(id)}/targets`, { indexes }))
    if (!r) return
    if (r.items.length === 0) return setNone(true)
    patch({ targets: r.items })
    next()
  }

  async function giveUp() { // 아무것도 고르지 못하는 신청은 서버에도 종료로 남긴다
    if (none || await run(() => callJson('POST', `${base(id)}/targets`, {})) !== undefined) nav('/loans')
  }

  if (none || (list && !eligible)) {
    return (
      <>
        <div className="ln-box ng"><b>대환 불가</b> 대환 가능한 대출이 없어요. 기존 금융사에 금리인하요구권을 쓰는 방법도 있어요.</div>
        {list && <ul className="ln-reasons">{list.map((l) => <li key={l.id}>{l.institution} {l.codes.map((c) => <code key={c}>{c}</code>)}</li>)}</ul>}
        <ErrBox err={err} />
        <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void giveUp()}>처음으로</button></div>
      </>
    )
  }
  const picked = (sel.map((i) => list![i]))
  return (
    <div className="auth-form">
      {list ? (
        <ul className="ln-list">
          {list.map((l, i) => (
            <li key={l.id}>
              <LoanRow l={l} right={l.codes.length === 0
                ? <label className="auth-check"><input type="checkbox" checked={sel.includes(i)} onChange={(e) => setSel((p) => (e.target.checked ? [...p, i] : p.filter((x) => x !== i)))} />대환 가능</label>
                : <span className="tag ng">대환 불가</span>} />
              {l.codes.length > 0 && <ul className="ln-reasons">{l.codes.map((c) => <li key={c}><code>{c}</code> {REASON[c]}</li>)}</ul>}
            </li>
          ))}
        </ul>
      ) : <p className="auth-notice">조회한 대출 목록을 다시 불러올 수 없어서, 대환 가능한 대출을 모두 선택해요.</p>}
      {picked.length > 0 && <p className="auth-notice">선택한 대출 잔액 합계 {won(picked.reduce((a, l) => a + l.balance, 0))} (중도상환수수료는 신청 금액에 더해져요)</p>}
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy || (!!list && sel.length === 0)} onClick={() => void submit(list ? sel : undefined)}>다음</button></div>
    </div>
  )
}

const DEFAULT_TERM = (opts: number[], remain?: number) => remain ? opts.reduce((a, b) => (Math.abs(b - remain) < Math.abs(a - remain) ? b : a)) : opts[Math.min(2, opts.length - 1)]

/** 고객정보 확인과 적합성 판정. 부적합이면 조정안을 고르거나 고지를 확인하고 진행한다. */
export function Profile() {
  const { id, product, stash, patch, next } = useFlow()
  const refi = product.businessType === 'REFI'
  const demo = !!stash.scenario // 체험 고객이면 서버가 그 고객의 값을 쓴다
  const remain = refi && stash.targets ? Math.max(...stash.targets.map((t) => t.remain)) : undefined
  const [f, setF] = useState({ job: JOBS[0], tenure: '36', income: '5000', debt: '0', amount: '', term: String(DEFAULT_TERM(product.termOptions, remain)), repay: product.repayOptions[0], ratePref: RATE_PREFS[0], delinq: false })
  const [res, setRes] = useState<ProfileResult | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [pick, setPick] = useState<'amount' | 'term' | 'ack'>('ack')
  const [ack, setAck] = useState(false)
  const { busy, err, run } = useRun()
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }))
  const amount = Number(f.amount || 0) * 10_000
  const amountErr = refi || demo || !f.amount ? null
    : amount > product.maxAmount ? `한도금액을 초과하였습니다. 이 상품의 최대 한도는 ${won(product.maxAmount)}입니다.`
    : amount < product.minAmount ? `희망 금액은 최소 ${won(product.minAmount)} 이상이어야 해요.` : null

  async function submit(extra: { amount?: number; term?: number; ackUnsuitable?: boolean } = {}, msg?: string) {
    const body = demo ? extra : {
      job: f.job, tenure: Number(f.tenure), income: Number(f.income) * 10_000, debtMonthly: Number(f.debt) * 10_000, ...(refi ? {} : { amount }),
      term: Number(f.term), repay: f.repay, ratePref: f.ratePref, delinq1y: f.delinq, ...extra,
    }
    const r = await run(() => callJson<ProfileResult>('POST', `${base(id)}/profile`, body))
    if (!r) return
    setRes(r); setNote(msg ?? null); setAck(false)
    if (extra.amount) set('amount', toMan(extra.amount))
    if (extra.term) set('term', String(extra.term))
    patch({ profile: { amount: extra.amount ?? (refi || demo ? undefined : amount), term: extra.term ?? (demo ? undefined : Number(f.term)), repay: demo ? undefined : f.repay } })
    const plan = r.adjustPlan
    setPick(plan?.maxAmount && !refi ? 'amount' : plan?.minTerm ? 'term' : 'ack')
  }

  if (res) {
    const plan = res.adjustPlan
    const pass = res.status === 'PROFILED'
    const label = { SUITABLE: '적합', WARNING: '주의', UNSUITABLE: '부적합' }[res.suitability]
    return (
      <div className="auth-form">
        <div className="ln-box">
          <div className="row"><b>적합성 1차 판정</b><span className={`tag ${res.suitability === 'SUITABLE' ? 'ok' : res.suitability === 'WARNING' ? 'wa' : 'ng'}`}>{label}</span></div>
          <p className="small">상환 부담률 {pct(res.burdenRatio)} (기준 70%)</p>
          <div className="bar thin"><i style={{ width: `${Math.min(res.burdenRatio / 0.7, 1) * 100}%`, background: res.burdenRatio > 0.7 ? '#d54d44' : undefined }} /></div>
          {res.suitability === 'WARNING' && <p className="small">최근 1년 연체 이력이 있어 심사에서 불리할 수 있어요.</p>}
        </div>
        {note && <p className="auth-flash" role="status">{note}</p>}
        {!pass && plan && (
          <>
            <p className="auth-notice">금소법 적합성 원칙에 따라 현재 조건으로는 상품을 권유할 수 없어요. 월 상환 가능액은 약 {won(plan.budget)}이에요. 아래 중에서 골라 주세요.</p>
            <div className="ac-pick">
              {plan.maxAmount && !refi && <button type="button" className={pick === 'amount' ? 'on' : ''} onClick={() => setPick('amount')}><span>금액을 {won(plan.maxAmount)} 이하로 조정<br /><small>기간 유지</small></span></button>}
              {plan.minTerm && <button type="button" className={pick === 'term' ? 'on' : ''} onClick={() => setPick('term')}><span>기간을 {plan.minTerm}개월로 조정<br /><small>금액 유지</small></span></button>}
              <button type="button" className={pick === 'ack' ? 'on' : ''} onClick={() => setPick('ack')}><span>조정 없이 현재 조건으로 심사 진행<br /><small>심사에서 거절될 수 있어요</small></span></button>
            </div>
            {pick === 'ack' && <label className="auth-check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />대출 업무 진행이 불가할 수 있는 점을 인지하고 있으며, 신용 조회 등 관련 심사 절차 진행에 동의합니다.</label>}
          </>
        )}
        <p className="small">※ 본 결과는 입력한 정보에 따른 결과이므로 심사 결과는 달라질 수 있어요.</p>
        <ErrBox err={err} />
        <div className="auth-actions">
          <button type="button" className="ghost" onClick={() => setRes(null)}>수정</button>
          {pass
            ? <button type="button" className="primary" onClick={() => next()}>다음</button>
            : <button type="button" className="primary" disabled={busy || (pick === 'ack' && !ack)} onClick={() => void (
              pick === 'amount' ? submit({ amount: plan!.maxAmount! }, `금액을 ${won(plan!.maxAmount!)}으로 조정했어요.`)
              : pick === 'term' ? submit({ term: plan!.minTerm! }, `기간을 ${plan!.minTerm}개월로 조정했어요.`)
              : submit({ ackUnsuitable: true }, '현재 조건으로 심사를 진행해요 (고지 확인 기록).'))}>다음</button>}
        </div>
      </div>
    )
  }

  return (
    <div className="auth-form">
      {demo ? <p className="auth-notice">체험 고객의 고객정보를 사용해요. 아래 버튼으로 적합성을 확인해 주세요.</p> : (
        <>
          <label className="auth-field">직업<select className="ac-select" value={f.job} onChange={(e) => set('job', e.target.value)}>{JOBS.map((j) => <option key={j}>{j}</option>)}</select></label>
          <label className="auth-field">재직(사업) 기간 (개월)<input inputMode="numeric" value={f.tenure} onChange={(e) => set('tenure', e.target.value.replace(/\D/g, ''))} /></label>
          <ManField label="연 소득" value={f.income} onChange={(v) => set('income', v)} />
          <ManField label="기존 대출 월 상환액" value={f.debt} onChange={(v) => set('debt', v)} />
          <Seg label="최근 1년 연체 이력" value={f.delinq} onChange={(v) => set('delinq', v)} options={[[false, '없음'], [true, '있음']]} />
          {refi
            ? <p className="auth-notice">대환 금액은 선택한 대출의 잔액과 중도상환수수료로 정해져요.{stash.targets && ` (잔액 합계 ${won(stash.targets.reduce((a, l) => a + l.balance, 0))})`}</p>
            : <ManField label="희망 금액" value={f.amount} onChange={(v) => set('amount', v)} hint={`최소 ${won(product.minAmount)} ~ 최대 ${won(product.maxAmount)}`} error={amountErr} />}
          <label className="auth-field">{refi ? '희망 대환 기간' : '희망 기간'}<select className="ac-select" value={f.term} onChange={(e) => set('term', e.target.value)}>{product.termOptions.map((t) => <option key={t} value={t}>{t}개월</option>)}</select></label>
          <label className="auth-field">상환 방법<select className="ac-select" value={f.repay} onChange={(e) => set('repay', e.target.value)}>{product.repayOptions.map((r) => <option key={r}>{r}</option>)}</select></label>
          <label className="auth-field">금리 선호<select className="ac-select" value={f.ratePref} onChange={(e) => set('ratePref', e.target.value)}>{RATE_PREFS.map((r) => <option key={r}>{r}</option>)}</select></label>
        </>
      )}
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy || (!demo && !refi && (!f.amount || !!amountErr)) || (!demo && (!f.income || !f.tenure))} onClick={() => void submit()}>적합성 확인</button></div>
    </div>
  )
}
