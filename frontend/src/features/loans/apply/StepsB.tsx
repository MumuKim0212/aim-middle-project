import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { koreanAmount, won } from '../../../format'
import { callJson } from '../../../lib/http'
import { errCode, useLoad } from '../../accounts/api'
import { uploadDoc } from '../api'
import { LoanLoad } from '../parts'
import { Ineligible } from './StepsA'
import { ORGS, REASON, VERDICT_TEXT, type Candidate, type Compare as CompareT, type GuaranteeOption, type ReviewResult } from './model'
import { ErrBox, Reasons, Seg, useFlow, useRun } from './shared'

const base = (id: string) => `/api/loans/applications/${id}`

/** (정부) 행정정보로 하는 정책 자격 검증. */
export function PolicyCheck() {
  const { id, next } = useFlow()
  const [passed, setPassed] = useState<boolean | null>(null)
  const { busy, err, run } = useRun()
  async function submit() {
    const r = await run(() => callJson<{ passed: boolean }>('POST', `${base(id)}/policy-check`))
    if (r) setPassed(r.passed)
  }
  if (passed === false) return <Ineligible title="정책 자격 미충족" codes={[]} />
  return (
    <div className="auth-form">
      {passed && <div className="ln-box ok">정책 자격 충족</div>}
      <ErrBox err={err} />
      <div className="auth-actions">
        {passed ? <button type="button" className="primary" onClick={() => next()}>다음</button>
          : <button type="button" className="primary" disabled={busy} onClick={() => void submit()}>{busy ? '확인하는 중…' : '정책 자격 검증'}</button>}
      </div>
    </div>
  )
}

/** (기관 A) 보증기관 비교와 선택. */
export function Guarantee() {
  const { id, next } = useFlow()
  const opts = useLoad<{ items: GuaranteeOption[] }>(`${base(id)}/guarantee-options`)
  const [sel, setSel] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [rejected, setRejected] = useState(false)
  const { busy, err, run } = useRun()
  if (!opts.data) return <LoanLoad error={opts.error} retry={opts.reload} />
  const items = opts.data.items
  const best = items.filter((o) => o.ok)[0]
  const pick = sel ?? best?.agency
  if (rejected || !best) return <Ineligible title="보증 불가" codes={['COL-DEPOSIT-OVER-VALUE']} />

  async function submit() {
    const r = await run(() => callJson<{ approved: boolean }>('POST', `${base(id)}/guarantee`, { agency: pick }))
    if (r) (r.approved ? next() : setRejected(true))
  }
  return (
    <div className="auth-form">
      <div className="ac-pick">
        {items.map((o) => (
          <button key={o.agency} type="button" className={`${pick === o.agency ? 'on' : ''}${o.ok ? '' : ' ln-off'}`} onClick={() => { if (o.ok) { setSel(o.agency); setMsg(null) } else setMsg('보증 대상 기준을 충족하지 않습니다') }}>
            <span>
              <b>{o.agency} 전세보증</b>{o === best && <span className="tag ok" style={{ marginLeft: 6 }}>실질 비용 최저</span>}<br />
              <small>보증 한도 {won(o.amount)} · 보증료율 연 {o.feeRate}%</small><br />
              <small>2년 이자 {won(o.interest)} · 2년 보증료 {won(o.fee)}</small><br />
              <small>실질 비용 <b>{won(o.cost)}</b></small>
            </span>
          </button>
        ))}
      </div>
      {msg && <p className="auth-err" role="alert">{msg}</p>}
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy || !pick} onClick={() => void submit()}>이 보증기관으로 진행</button></div>
    </div>
  )
}

/** (기관 B) 협약기관 재직 확인. */
export function Affiliation() {
  const { id, next } = useFlow()
  const [f, setF] = useState({ orgId: '', empNo: '', empType: '정규직' })
  const [ok, setOk] = useState<boolean | null>(null)
  const { busy, err, run } = useRun()
  async function submit() {
    const r = await run(() => callJson<{ passed: boolean }>('POST', `${base(id)}/affiliation`, f))
    if (r) setOk(r.passed)
  }
  if (ok === false) return <Ineligible title="협약 대상이 아니에요" codes={['ORG-EMP-TYPE']} />
  const org = ORGS.find(([c]) => c === f.orgId)?.[1]
  return (
    <div className="auth-form">
      {ok ? <div className="ln-box ok"><b>재직 확인 완료</b> {org} · {f.empType} · 협약 금리 적용 대상</div> : (
        <>
          <label className="auth-field">협약기관
            <select className="ac-select" value={f.orgId} onChange={(e) => setF((p) => ({ ...p, orgId: e.target.value }))}>
              <option value="">협약기관을 선택하세요</option>
              {ORGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
          </label>
          <label className="auth-field">사번<input value={f.empNo} autoComplete="off" onChange={(e) => setF((p) => ({ ...p, empNo: e.target.value }))} /></label>
          <Seg label="고용 형태" value={f.empType} onChange={(v) => setF((p) => ({ ...p, empType: v }))} options={[['정규직', '정규직'], ['계약직', '계약직']]} />
        </>
      )}
      <ErrBox err={err} />
      <div className="auth-actions">
        {ok ? <button type="button" className="primary" onClick={() => next()}>다음</button>
          : <button type="button" className="primary" disabled={busy || !f.orgId || !f.empNo} onClick={() => void submit()}>협약기관 재직 확인</button>}
      </div>
    </div>
  )
}

type Doc = { key: string; name: string; req: boolean; auto: boolean; sample: string }

/** 증빙 제출: 자동 연동 또는 파일 업로드(서류마다 1건). 체험 고객이면 샘플 서류가 자동으로 붙는다. */
export function Docs() {
  const { id, stash, next } = useFlow()
  const docs = useLoad<{ items: Doc[] }>(`${base(id)}/docs`)
  const [files, setFiles] = useState<Record<string, string>>({})
  const [auto, setAuto] = useState(false)
  const [defects, setDefects] = useState<string[] | null>(null)
  const { busy, err, run } = useRun()
  const demo = !!stash.scenario
  const noConsent = errCode(err) === 'LOAN_CONSENT_REQUIRED'
  const canAuto = !noConsent && (!stash.agreed || stash.agreed.includes('PUBLIC_SCRAPING'))
  const linked = auto && canAuto
  if (!docs.data) return <LoanLoad error={docs.error} retry={docs.reload} />

  async function upload(key: string, file: File) {
    const r = await run(() => uploadDoc(id, key, file))
    if (r) setFiles((p) => ({ ...p, [key]: file.name }))
  }
  async function submit() {
    const r = await run(() => callJson<{ defects: string[] }>('POST', `${base(id)}/docs`, { autoLink: linked }))
    if (r) setDefects(r.defects)
  }

  if (defects) {
    return (
      <>
        {defects.length === 0 ? <div className="ln-box ok">서류 결함 없음</div>
          : <div className="ln-box wa"><b>발견된 결함 {defects.length}건</b><Reasons codes={defects} text={REASON} /></div>}
        <div className="auth-actions"><button type="button" className="primary" onClick={() => next()}>심사 시작</button></div>
      </>
    )
  }
  return (
    <div className="auth-form">
      {demo && <p className="auth-notice">체험 고객의 서류가 자동으로 제출돼요.</p>}
      {canAuto && <label className="auth-check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />공공기관 자동 연동 사용 (건강보험·국세청)</label>}
      <ul className="ln-list">
        {docs.data.items.map((d) => (
          <li key={d.key} className="ln-doc">
            <div>
              <strong>{d.name}</strong><span className={`tag ${d.req ? '' : 'ok'}`}>{d.req ? '필수' : '선택'}</span>
              <small>{linked && d.auto ? '공공기관 연동 · 제출 생략' : files[d.key] ?? (demo ? `${d.sample} (체험 고객)` : '파일을 선택해 주세요')}</small>
            </div>
            {!(linked && d.auto) && !demo && (
              <label className="ln-file">{files[d.key] ? '다시 선택' : '파일 선택'}
                <input type="file" hidden accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" disabled={busy}
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void upload(d.key, f) }} />
              </label>
            )}
          </li>
        ))}
      </ul>
      {noConsent ? <p className="auth-err" role="alert">자동 연동에 동의하지 않아 연동할 수 없어요. 서류를 직접 올려 주세요.</p> : <ErrBox err={err} />}
      <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void submit()}>서류 제출</button></div>
    </div>
  )
}

const MARK = { ok: '✓', wa: '!', ng: '✕' }

/** 심사 실행과 단계별 결과. */
export function Review() {
  const { id, patch, next } = useFlow()
  const [r, setR] = useState<ReviewResult | null>(null)
  const { busy, err, run } = useRun()
  async function submit() {
    const res = await run(() => callJson<ReviewResult>('POST', `${base(id)}/review`))
    if (res) { setR(res); patch({ review: res }) }
  }
  return (
    <div className="auth-form">
      {r && (
        <ul className="ln-stage">
          {r.stages.map((s) => <li key={s.name} className={s.mark}><i>{MARK[s.mark]}</i><div><strong>{s.name}</strong><small>{s.name === '판정' ? VERDICT_TEXT[s.text] ?? s.text : s.text}</small></div></li>)}
        </ul>
      )}
      <ErrBox err={err} />
      <div className="auth-actions">
        {r ? <button type="button" className="primary" onClick={() => next()}>결과 보기</button>
          : <button type="button" className="primary" disabled={busy} onClick={() => void submit()}>{busy ? '심사 중…' : '심사 시작'}</button>}
      </div>
    </div>
  )
}

/** 거절·서류 보완 판정 화면(result·compare 공통). */
function Verdict({ r, status }: { r?: ReviewResult; status: string }) {
  const { goStep } = useFlow()
  if (status === 'DOCS_REQUIRED') {
    return (
      <>
        <div className="ln-box wa"><b>서류 보완이 필요해요</b> 아래 서류를 다시 내면 처음부터 다시 심사해요.<Reasons codes={r?.docCodes ?? []} text={REASON} /></div>
        <div className="auth-actions"><button type="button" className="primary" onClick={() => goStep('docs')}>서류 다시 제출</button></div>
      </>
    )
  }
  return (
    <>
      <div className="ln-box ng"><b>승인되지 않았어요</b> 보완해도 결과가 바뀌지 않는 사유가 있어요.<Reasons codes={r?.hardCodes ?? []} text={REASON} /></div>
      {!!r?.docCodes.length && <div className="ln-box"><b>함께 발견된 서류 결함 (참고)</b><Reasons codes={r.docCodes} text={REASON} /></div>}
      <p className="small">근거 신용정보 제공 기관: NICE평가정보(가상) / 한국신용정보원. 자동화 평가 결과에 대해 설명을 요구하거나 정보 정정 후 재평가를 요청할 수 있어요.</p>
      <div className="auth-stack"><Link to="/loans" className="auth-btn">처음으로</Link></div>
    </>
  )
}

function ApprovalBox({ r, status }: { r?: ReviewResult; status: string }) {
  return (
    <div className="ln-box ok">
      <b>{status === 'COND_APPROVED' ? '조건부 승인' : '승인'}</b>
      {r && <p className="small">승인 한도 {won(r.limit)} · 예상 금리 연 {r.rate}%{status === 'COND_APPROVED' && ' → 신청 금액보다 한도가 작아 감액돼요.'}</p>}
      {!!r?.conditionCodes.length && <Reasons codes={r.conditionCodes} text={REASON} />}
    </div>
  )
}

/** 심사 결과와 권장 상품 3안 중 선택. */
export function Result() {
  const { id, product, stash, app, next } = useFlow()
  const r = stash.review
  const status = r?.result ?? app?.status ?? ''
  if (status === 'REJECTED' || status === 'DOCS_REQUIRED') return <Verdict r={r} status={status} />
  return <Recs id={id} name={product.name.split(' (')[0]} head={<ApprovalBox r={r} status={status} />} done={next} />
}

function Recs({ id, name, head, done }: { id: string; name: string; head: ReactNode; done: () => void }) {
  const recs = useLoad<{ items: Candidate[] }>(`${base(id)}/recommendations`)
  const [sel, setSel] = useState<string | null>(null)
  const { busy, err, run } = useRun()
  if (!recs.data) return <LoanLoad error={recs.error} retry={recs.reload} />
  const pick = sel ?? recs.data.items[0]?.variant
  async function submit() {
    if (await run(() => callJson('POST', `${base(id)}/choose`, { variant: pick })) !== undefined) done()
  }
  return (
    <div className="auth-form">
      {head}
      <h3 className="ln-sub">고객님께 권장하는 상품 <small>총 이자 기준 · 수익성 미반영</small></h3>
      <div className="ac-pick">
        {recs.data.items.map((c, i) => (
          <button key={c.variant} type="button" className={pick === c.variant ? 'on' : ''} onClick={() => setSel(c.variant)}>
            <span>
              <b>{name} · {c.variant}</b>{i === 0 && <span className="tag ok" style={{ marginLeft: 6 }}>조건에 가장 유리</span>}<br />
              <small>금리 연 {c.rate}% ({c.rateType}) · 월 상환 {won(c.monthly)}</small><br />
              <small>총 이자 {won(c.totalInterest)} · 추천 점수 {Math.round(c.score * 100)}</small>
              {c.reasons.map((t) => <small key={t} className="ln-line">{t}</small>)}
              {c.cautions.map((t) => <small key={t} className="ln-line">주의: {t}</small>)}
            </span>
          </button>
        ))}
      </div>
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy || !pick} onClick={() => void submit()}>이 상품으로 진행</button></div>
    </div>
  )
}

const VERDICT = {
  BENEFICIAL: ['ok', '갈아타면 이득'], TRADE_OFF: ['wa', '월 부담만 감소'], NOT_BENEFICIAL: ['ng', '갈아타면 손해'],
} as const

/** (대환) 갈아타기 유불리 비교. 불리하면 고지를 확인해야 진행된다. */
export function Compare() {
  const { id, stash, app, next } = useFlow()
  const r = stash.review
  const status = r?.result ?? app?.status ?? ''
  const blocked = status === 'REJECTED' || status === 'DOCS_REQUIRED'
  const [c, setC] = useState<CompareT | null>(null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [tick, setTick] = useState(0)
  const [ok, setOk] = useState(false)
  const { busy, err, run } = useRun()
  useEffect(() => {
    if (blocked) return
    let alive = true
    setLoadErr(null)
    callJson<CompareT>('POST', `${base(id)}/compare`, { confirmUnfavorable: false }).then((d) => alive && setC(d)).catch((e) => alive && setLoadErr(e))
    return () => { alive = false }
  }, [id, blocked, tick])
  if (blocked) return <Verdict r={r} status={status} />
  if (!c) return loadErr ? <><ErrBox err={loadErr} /><button type="button" className="ac-retry" onClick={() => setTick((n) => n + 1)}>다시 시도</button></> : <div className="state">불러오는 중…</div>
  const [tone, title] = VERDICT[c.verdict]
  const good = c.verdict === 'BENEFICIAL'
  const row = (name: string, a: string, b: string, better?: boolean) => <tr key={name}><th>{name}</th><td>{a}</td><td className={better === undefined ? '' : better ? 'good' : 'bad'}>{b}</td></tr>

  async function proceed() {
    if (await run(() => callJson('POST', `${base(id)}/compare`, { confirmUnfavorable: true })) !== undefined) next()
  }
  return (
    <div className="auth-form">
      <div className={`ln-box ${tone}`}><b>{title}</b><p className="small">순 절감액 {won(c.net)}{good && c.breakEven && ` · ${c.breakEven}개월째부터 이득`}</p></div>
      <table className="ln-cmp">
        <thead><tr><th /><th>기존</th><th>대환 후</th></tr></thead>
        <tbody>
          {row('기간', `남은 ${c.remain}개월`, `${c.term}개월`)}
          {row('금리', `연 ${c.oldRate}%`, `연 ${c.newRate}%`, true)}
          {row('월 납입액', won(c.oldMonthly), won(c.newMonthly), c.newMonthly <= c.oldMonthly)}
          {row('남은 총 이자', won(c.oldInterest), won(c.newInterest), c.newInterest <= c.oldInterest)}
          {row('대환 비용', '-', won(c.cost))}
          {row('순 절감액', '', won(c.net), c.net > 0)}
        </tbody>
      </table>
      <p className="small">대환 비용: 중도상환수수료 {won(c.fee)} + 인지세 {won(c.stamp)} (예시) · 대환 금액 {koreanAmount(c.principal)}</p>
      {c.message.reasons.map((t) => <p key={t} className="small">{t}</p>)}
      {c.message.cautions.map((t) => <p key={t} className="small">주의: {t}</p>)}
      {!good && <label className="auth-check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />불리하다는 고지를 확인했으며 그래도 진행합니다</label>}
      <ErrBox err={err} />
      <div className="auth-actions">
        {good ? <button type="button" className="primary" onClick={() => next()}>다음</button>
          : <button type="button" className="primary" disabled={!ok || busy} onClick={() => void proceed()}>대환 진행</button>}
      </div>
    </div>
  )
}
