import { useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { won } from '../../../format'
import { callJson } from '../../../lib/http'
import { accountName, errCode, useLoad, type Account } from '../../accounts/api'
import { PinDialog } from '../../accounts/parts'
import { postIdem, type Loan } from '../api'
import { LoanLoad } from '../parts'
import { writeLast, PREFS } from './model'
import { ErrBox, ManField, dot, toMan, useFlow, useRun } from './shared'

const base = (id: string) => `/api/loans/applications/${id}`
const checking = (list: { items: Account[] }) => list.items.filter((a) => a.productType === 'checking' && a.status === 'active')

/** 확정한 조건 요약(GET /applications/{id} 의 terms·finalRate). */
function TermsSummary() {
  const { app, product, stash, step } = useFlow()
  const t = app?.terms
  if (!t) return null
  return (
    <dl className="auth-summary">
      <div><dt>상품</dt><dd>{product.name}</dd></div>
      <div><dt>대출 금액</dt><dd><b>{won(t.amount)}</b></dd></div>
      {app.finalRate != null && <div><dt>최종 금리</dt><dd>연 {app.finalRate}%</dd></div>}
      <div><dt>대출 기간</dt><dd>{t.term}개월</dd></div>
      <div><dt>상환 방법</dt><dd>{t.repay}</dd></div>
      {stash.monthly != null && step !== 'pricing' && <div><dt>월 상환액</dt><dd>{won(stash.monthly)}</dd></div>}
    </dl>
  )
}

/** 금액·기간·상환 방법·납입일·자동이체 계좌. 서버가 승인 한도 안인지 확인한다. */
export function Terms() {
  const { id, product, stash, next } = useFlow()
  const refi = product.businessType === 'REFI'
  const accounts = useLoad<{ items: Account[] }>('/api/accounts')
  const limit = stash.review?.limit
  const wanted = stash.profile?.amount
  const [f, setF] = useState({ amount: wanted ? toMan(limit ? Math.min(wanted, limit) : wanted) : '', term: String(stash.profile?.term ?? ''), repay: stash.profile?.repay ?? '', day: '25', debit: '' })
  const { busy, err, run } = useRun()
  if (!accounts.data) return <LoanLoad error={accounts.error} retry={accounts.reload} />
  const list = checking(accounts.data)
  const debit = f.debit || String((list.find((a) => a.isPrimary) ?? list[0])?.accountId ?? '')
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }))

  async function submit() {
    const body = {
      ...(!refi && f.amount ? { amount: Number(f.amount) * 10_000 } : {}), ...(f.term ? { term: Number(f.term) } : {}), ...(f.repay ? { repay: f.repay } : {}),
      paymentDay: Number(f.day), ...(debit ? { debitAccountId: Number(debit) } : {}),
    }
    if (await run(() => callJson('POST', `${base(id)}/terms`, body)) !== undefined) next()
  }
  return (
    <div className="auth-form">
      {refi
        ? <p className="auth-notice">대환 금액은 기존 대출 상환에 필요한 금액으로 정해져요.</p>
        : <ManField label="대출 금액" value={f.amount} onChange={(v) => set('amount', v)} hint={limit ? `승인 한도 ${won(limit)} · 비워 두면 신청한 금액(한도 안)` : '비워 두면 신청한 금액(승인 한도 안)'} />}
      <label className="auth-field">대출 기간
        <select className="ac-select" value={f.term} onChange={(e) => set('term', e.target.value)}>
          {!stash.profile?.term && <option value="">신청한 기간 그대로</option>}
          {product.termOptions.map((t) => <option key={t} value={t}>{t}개월</option>)}
        </select>
      </label>
      <label className="auth-field">상환 방법
        <select className="ac-select" value={f.repay} onChange={(e) => set('repay', e.target.value)}>
          {!stash.profile?.repay && <option value="">신청한 방법 그대로</option>}
          {product.repayOptions.map((r) => <option key={r}>{r}</option>)}
        </select>
      </label>
      <label className="auth-field">매월 납입일
        <select className="ac-select" value={f.day} onChange={(e) => set('day', e.target.value)}>{[5, 10, 15, 20, 25].map((d) => <option key={d} value={d}>{d}일</option>)}</select>
      </label>
      <label className="auth-field">자동이체 출금 계좌
        <select className="ac-select" value={debit} onChange={(e) => set('debit', e.target.value)}>
          {list.length === 0 && <option value="">출금할 저축예금이 없어요</option>}
          {list.map((a) => <option key={a.accountId} value={a.accountId}>{accountName(a)} {a.accountMasked}</option>)}
        </select>
      </label>
      <p className="small">자동이체 출금 동의가 함께 기록돼요.</p>
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void submit()}>다음</button></div>
    </div>
  )
}

/** 우대 금리 선택 후 최종 금리·월 상환액 확정. */
export function Pricing() {
  const { id, patch, next } = useFlow()
  const [prefs, setPrefs] = useState(['AUTO_DEBIT'])
  const [res, setRes] = useState<{ finalRate: number; monthly: number } | null>(null)
  const { busy, err, run } = useRun()
  async function submit() {
    const r = await run(() => callJson<{ finalRate: number; monthly: number }>('POST', `${base(id)}/price`, { prefs }))
    if (r) { setRes(r); patch({ monthly: r.monthly }) }
  }
  return (
    <div className="auth-form">
      <TermsSummary />
      {res ? (
        <>
          <dl className="auth-summary">
            <div><dt>최종 금리</dt><dd><b>연 {res.finalRate}%</b></dd></div>
            <div><dt>월 상환액</dt><dd><b>{won(res.monthly)}</b></dd></div>
          </dl>
          <p className="small">약속형 우대 조건을 지키지 못하면 다음 금리 변경일에 해당 우대가 빠져요.</p>
          <div className="auth-actions"><button type="button" className="primary" onClick={() => next()}>다음</button></div>
        </>
      ) : (
        <>
          <div className="auth-terms">
            {PREFS.map(([code, label]) => (
              <label key={code}><input type="checkbox" checked={prefs.includes(code)} onChange={(e) => setPrefs((p) => (e.target.checked ? [...p, code] : p.filter((x) => x !== code)))} />{label}</label>
            ))}
          </div>
          <ErrBox err={err} />
          <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void submit()}>금리 확정</button></div>
        </>
      )}
    </div>
  )
}

/** 상품설명서를 끝까지 읽고 O/X 확인 문제를 푼다(정답은 서버가 판정). */
export function Explain() {
  const { id, product, app, next } = useFlow()
  const quiz = useLoad<{ items: string[] }>(`${base(id)}/quiz`)
  const [read, setRead] = useState(false)
  const [ans, setAns] = useState<string[]>([])
  const { busy, err, run } = useRun()
  if (!quiz.data) return <LoanLoad error={quiz.error} retry={quiz.reload} />
  const refi = product.businessType === 'REFI'
  const policy = product.businessType === 'POLICY'
  const t = app?.terms
  const ready = read && quiz.data.items.every((_, i) => ans[i])
  const secs: [string, string][] = [
    ['상품 개요', `${product.name}은(는) ${product.targetDesc}를 대상으로 하는 대출이에요.`],
    ['금리', policy ? '정책 금리표에 따르며 공고 변경 시 다음 금리 변경일부터 적용될 수 있어요.' : '기준금리 + 가산금리 − 우대금리로 정해요. 변동금리는 기준금리 변동 주기마다 다시 정해져요.'],
    ['상환과 수수료', `중도상환수수료 = 상환 원금 × 수수료율 × 남은 기간 ÷ 대출 기간. 계약일로부터 3년이 지나면 부과하지 않아요.${refi ? ' 기존 대출의 중도상환수수료는 고객이 부담해요.' : ''}`],
    ['연체 시 불이익', `지연배상금(약정 금리 + 연 3%p)이 붙고, 연체가 이어지면 기한의 이익이 상실될 수 있어요.${product.collateralType === 'CREDIT' ? '' : ' 담보물이 법정 절차로 처분될 수 있어요.'}`],
    ...(policy ? [['정책 의무', '실행 후 정해진 기간 안에 전입·실거주해야 하며, 추가 주택을 취득하면 대출금이 회수될 수 있어요.'] as [string, string]]
      : product.instKind === 'B' ? [['협약 특약', '퇴직·휴직·협약 해지 시 일반 금리로 전환되거나 상환 방법을 협의해요.'] as [string, string]]
      : product.instKind === 'A' ? [['보증', '보증료가 별도로 들며, 보증 사고 시 보증기관이 고객에게 구상권을 행사할 수 있어요.'] as [string, string]] : []),
    ['고객의 권리', '청약철회권(14일), 금리인하요구권, 위법계약해지권, 자료열람요구권이 있어요.'],
  ]
  async function submit() {
    if (await run(() => callJson('POST', `${base(id)}/explain`, { scrolled: read, answers: ans })) !== undefined) next()
  }
  return (
    <div className="auth-form">
      {t && (
        <dl className="auth-summary">
          <div><dt>대출 금액</dt><dd>{won(t.amount)}</dd></div>
          <div><dt>대출 기간</dt><dd>{t.term}개월</dd></div>
          {app?.finalRate != null && <><div><dt>최종 금리</dt><dd>연 {app.finalRate}%</dd></div><div><dt>연체 이자</dt><dd>연 {(app.finalRate + 3).toFixed(2)}%</dd></div></>}
          <div><dt>중도상환수수료</dt><dd>3년 이내 부과</dd></div>
        </dl>
      )}
      <div className="ln-scroll" tabIndex={0} aria-label="상품설명서" onScroll={(e) => { const el = e.currentTarget; if (el.scrollTop + el.clientHeight >= el.scrollHeight - 6) setRead(true) }}>
        {secs.map(([h, p], i) => <section key={h}><h4>{h === '고객의 권리' ? h : `${i + 1}. ${h}`}</h4><p>{p}</p></section>)}
        <p className="end">— 끝까지 읽었습니다 —</p>
      </div>
      <span className={`tag ${read ? 'ok' : ''}`}>{read ? '끝까지 읽음' : '아래로 끝까지 스크롤하세요'}</span>
      <ol className="ln-quiz">
        {quiz.data.items.map((q, i) => (
          <li key={q}>
            <p>{q}</p>
            <div className="ln-seg">
              {['O', 'X'].map((v) => <button key={v} type="button" className={ans[i] === v ? 'on' : ''} aria-pressed={ans[i] === v} onClick={() => setAns((p) => Object.assign([...p], { [i]: v }))}>{v}</button>)}
            </div>
          </li>
        ))}
      </ol>
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={!ready || busy} onClick={() => void submit()}>설명을 이해했습니다</button></div>
    </div>
  )
}

/** 약정 확인 체크 후 전자서명(데모). */
export function Contract() {
  const { id, product, patch, next } = useFlow()
  const refi = product.businessType === 'REFI'
  const lines = [
    '대출 금액·금리·기간·상환 방법을 확인했습니다.', '연체 시 지연배상금과 기한의 이익 상실에 대해 들었습니다.',
    '중도상환수수료와 청약철회권에 대해 들었습니다.', '약관과 상품설명서를 받았습니다.',
    ...(refi ? ['대출금은 기존 대출 상환에만 쓰이며, 상환이 실패하면 대환대출이 취소됩니다.'] : []),
  ]
  const [on, setOn] = useState<boolean[]>(lines.map(() => false))
  const { busy, err, run } = useRun()
  async function submit() {
    const r = await run(() => callJson<{ contractNo: string }>('POST', `${base(id)}/contract`, { confirmations: on }))
    if (r) { patch({ contractNo: r.contractNo }); next() }
  }
  return (
    <div className="auth-form">
      <TermsSummary />
      <div className="auth-terms">
        {lines.map((t, i) => <label key={t}><input type="checkbox" checked={on[i]} onChange={(e) => setOn((p) => p.map((v, j) => (j === i ? e.target.checked : v)))} />{t}</label>)}
      </div>
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={!on.every(Boolean) || busy} onClick={() => void submit()}>전자서명하고 약정 완료</button></div>
    </div>
  )
}

const COLLATERAL: Record<string, string[]> = {
  MORTGAGE: ['근저당권 설정계약', '법무사 배정', '전자등기 접수', '접수번호 확인'],
  'MORTGAGE-REFI': ['새 담보 서류 접수·담보 재평가', '법무사 일정 확정', '말소·설정 등기 동시 접수 준비'],
  JEONSE: ['보증 신청', '보증 심사 승인', '보증서 발급', '임대인 채권양도 통지·확인'],
  AUTO: ['저당권 설정계약', '자동차 저당 등록'],
  DEPOSIT: ['질권설정 승낙', '담보 예금 지급 정지 표시'],
}

/** 담보·보증 설정. */
export function Collateral() {
  const { id, product, next } = useFlow()
  const lines = COLLATERAL[product.businessType === 'REFI' && product.collateralType === 'MORTGAGE' ? 'MORTGAGE-REFI' : product.collateralType] ?? []
  const { busy, err, run } = useRun()
  async function submit() {
    if (await run(() => callJson('POST', `${base(id)}/collateral`)) !== undefined) next()
  }
  return (
    <div className="auth-form">
      <ol className="ln-quiz">{lines.map((l) => <li key={l}><p>{l}</p></li>)}</ol>
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy} onClick={() => void submit()}>{busy ? '설정하는 중…' : '담보·보증 설정'}</button></div>
    </div>
  )
}

const PAYEE: Record<string, string> = { JEONSE: '임대인 계좌', MORTGAGE: '주택 매도인 계좌', AUTO: '자동차 판매사 계좌' }

/** 대출 실행. 간편비밀번호 재확인과 Idempotency-Key 가 필요하고, 본인 지급 상품은 받을 계좌를 고른다. */
export function Execute() {
  const { id, product, patch, next } = useFlow()
  const refi = product.businessType === 'REFI'
  const self = !refi && (product.collateralType === 'CREDIT' || product.collateralType === 'DEPOSIT')
  const accounts = useLoad<{ items: Account[] }>('/api/accounts')
  const [acct, setAcct] = useState('')
  const [key] = useState(() => crypto.randomUUID()) // 이 화면에서 한 번 만든다. 비밀번호 확인 전에 거절된 요청은 키를 쓰지 않으므로 다시 보내도 된다
  const [pin, setPin] = useState(false)
  const sending = useRef(false) // 돈이 움직이는 요청이라 겹쳐 보내지 않는다(더블 클릭, 비밀번호 확인 콜백 중복)
  const { busy, err, run } = useRun()
  if (!accounts.data) return <LoanLoad error={accounts.error} retry={accounts.reload} />
  const list = checking(accounts.data)
  const to = acct || String((list.find((a) => a.isPrimary) ?? list[0])?.accountId ?? '')

  async function submit() {
    if (sending.current) return
    sending.current = true
    setPin(false)
    const r = await run(() => postIdem<{ contractNo: string }>(`${base(id)}/execute`, { accountId: self ? Number(to) : undefined }, key),
      (x) => { const need = errCode(x) === 'PIN_VERIFICATION_REQUIRED'; if (need) setPin(true); return need })
    sending.current = false
    if (!r) return
    writeLast(null)
    patch({ contractNo: r.contractNo })
    next({ contractNo: r.contractNo })
  }
  return (
    <div className="auth-form">
      <TermsSummary />
      {self ? (
        <label className="auth-field">대출금을 받을 계좌
          <select className="ac-select" value={to} onChange={(e) => setAcct(e.target.value)}>
            {list.length === 0 && <option value="">입금할 저축예금이 없어요</option>}
            {list.map((a) => <option key={a.accountId} value={a.accountId}>{accountName(a)} {a.accountMasked} · {won(a.balance)}</option>)}
          </select>
        </label>
      ) : <p className="auth-notice">{refi ? '대출금은 기존 금융사 상환 계좌로 지급돼요. 새 대출 실행과 기존 대출 상환은 하나로 처리돼요.' : `대출금은 ${PAYEE[product.collateralType]}로 지급돼요.`}</p>}
      <ErrBox err={err} />
      <div className="auth-actions"><button type="button" className="primary" disabled={busy || (self && !to)} onClick={() => void submit()}>{busy ? '실행하는 중…' : '대출 실행'}</button></div>
      {pin && <PinDialog desc={`${product.name} 대출 실행`} onVerified={() => void submit()} onCancel={() => setPin(false)} />}
    </div>
  )
}

/** (대환) 기존 대출 완제 확인. 화면에서 이어 받은 대상 목록만 보여 준다. */
export function Payoff() {
  const { stash, next } = useFlow()
  return (
    <div className="auth-form">
      <ul className="ln-list">
        {(stash.targets ?? []).map((l) => (
          <li key={l.id} className="ln-loan"><div><strong>{l.institution}</strong><small>{l.kind} · 상환 원금 {won(l.balance)}</small></div><span className="tag ok">완제</span></li>
        ))}
      </ul>
      <p className="auth-notice">기존 대출에 연결된 자동이체는 기존 금융사에서 해지해 주세요.</p>
      <div className="auth-actions"><button type="button" className="primary" onClick={() => next()}>다음</button></div>
    </div>
  )
}

const WITHDRAW_DAYS = 14 // 서버(loan/config.py WITHDRAW_DAYS)와 같다

/** 실행 완료. 새 대출 상세로 이어 준다. */
export function Done() {
  const { product, stash } = useFlow()
  const no = (useLocation().state as { contractNo?: string } | null)?.contractNo ?? stash.contractNo
  const loan = useLoad<Loan>(no ? `/api/loans/${no}` : null)
  const refi = product.businessType === 'REFI'
  const l = loan.data
  const until = l && (() => { const d = new Date(l.startDate); d.setUTCDate(d.getUTCDate() + WITHDRAW_DAYS); return dot(d.toISOString().slice(0, 10)) })()
  return (
    <div className="ln-done">
      <div className="ln-check" aria-hidden>✓</div>
      <h3>{refi ? '대환이 완료되었어요' : '대출이 실행되었어요'}</h3>
      {l && (
        <dl className="auth-summary">
          <div><dt>대출 계좌</dt><dd>{l.accountMasked}</dd></div>
          <div><dt>대출 금액</dt><dd><b>{won(l.principal)}</b></dd></div>
          <div><dt>금리</dt><dd>연 {l.rate}%</dd></div>
          <div><dt>대출 기간</dt><dd>{l.termMonths}개월 · {l.repayMethod}</dd></div>
          {l.nextDueDate && <div><dt>다음 상환일</dt><dd>{dot(l.nextDueDate)}</dd></div>}
          <div><dt>청약철회 기한</dt><dd>{until}</dd></div>
        </dl>
      )}
      {loan.error != null && <p className="small">대출 정보를 불러오지 못했어요. 내 대출에서 확인해 주세요.</p>}
      {refi && <p className="auth-notice">대환대출을 청약철회해도 이미 갚은 기존 대출은 되살아나지 않아요.</p>}
      <div className="auth-stack">
        {no && <Link to={`/loans/${no}`} className="ac-link-btn">내 대출 상세 보기</Link>}
        <Link to="/loans" className="auth-btn">내 대출 목록</Link>
      </div>
    </div>
  )
}
