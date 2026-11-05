import { useEffect, useRef, useState, type FormEvent } from 'react'
import { won } from '../../format'
import { checkPayment, fetchMode, fetchSummary, saveMode, type Mode, type Summary } from './api'
import {
  ANSWER_LABEL, CATEGORIES, HERO, MODE_LABEL, MODES, REWARD_BODY, REWARD_TITLE, WARNING_TITLE,
  answerFor, metrics, paymentFeedback, riskText, warningLevelLabel, type Entry,
} from './copy'
import { classify, findCategory, parseAmount } from './nlu'
import './ledger.css'

type Tab = 'summary' | 'chat' | 'history'
const TABS: { key: Tab; label: string }[] = [
  { key: 'summary', label: '요약' },
  { key: 'chat', label: '물어보기' },
  { key: 'history', label: '소비 내역' },
]
const PLACEHOLDER = '오늘 배달 2만 원 시켜도 돼?'
const HERO_IMAGE: Partial<Record<Mode, string>> = {
  roast: '/ledger/hell-gate.webp',
  basic: '/ledger/bank-glass.webp',
  kind: '/ledger/cute-pig.webp',
}
const FLOW_CATEGORIES = ['배달', '쇼핑', '생활', '장보기']

function shiftMonth(delta: number): string {
  const d = new Date()
  const t = new Date(d.getFullYear(), d.getMonth() + delta, 1)
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}`
}

export default function LedgerPage() {
  const [mode, setModeState] = useState<Mode>('roast')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [initial, setInitial] = useState<Entry | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [tab, setTab] = useState<Tab>('summary')
  const [question, setQuestion] = useState('')
  const [error, setError] = useState<string | null>(null)
  const lastCategory = useRef('배달')

  useEffect(() => {
    Promise.all([fetchSummary(), fetchMode(), checkPayment(20000, '배달', false)])
      .then(([s, md, chk]) => {
        setSummary(s)
        setModeState(md)
        setInitial({ text: PLACEHOLDER, intent: 'purchase', amount: 20000, category: '배달', check: chk })
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const changeMode = (md: Mode) => {
    setModeState(md)
    saveMode(md).catch(() => undefined) // 저장 실패해도 화면 전환은 유지
  }

  async function history(kind: 'last' | 'prev2'): Promise<Entry['history']> {
    const back = kind === 'last' ? 1 : 2
    const [cur, before] = await Promise.all([fetchSummary(shiftMonth(-back)), fetchSummary(shiftMonth(-back - 1))])
    const top = [...cur.categories].sort((a, b) => b.spent - a.spent)[0]
    return {
      month: cur.month,
      spent: cur.budget.spent,
      delta: cur.budget.spent - before.budget.spent,
      topName: top && top.spent > 0 ? top.category : '없음',
      topAmount: top?.spent ?? 0,
    }
  }

  async function ask(raw: string) {
    const text = raw.trim() || PLACEHOLDER
    const found = findCategory(text)
    if (found) lastCategory.current = found
    const category = found ?? lastCategory.current
    const intent = classify(text)
    const amount = parseAmount(text)
    const entry: Entry = { text, intent, amount, category }
    try {
      if (intent === 'purchase' && amount !== null) entry.check = await checkPayment(amount, category, false)
      if (intent === 'last' || intent === 'prev2') entry.history = await history(intent)
    } catch (e) {
      setError((e as Error).message)
      return
    }
    setEntries((p) => [...p, entry].slice(-24))
    setQuestion('')
  }

  if (error) {
    return (
      <div className="state">
        <p>데이터를 불러오지 못했어요.</p>
        <small>{error} · 백엔드(8000)가 켜져 있는지 확인하세요.</small>
      </div>
    )
  }
  if (!summary || !initial) return <div className="state">불러오는 중…</div>

  const current = entries[entries.length - 1] ?? initial
  const m = metrics(summary)
  const level = summary.risk.level

  return (
    <div className="lg" data-mode={mode}>
      <nav className="lg-tabs" aria-label="가계부 메뉴">
        {TABS.map((t) => (
          <button key={t.key} type="button" className={tab === t.key ? 'on' : ''} aria-current={tab === t.key ? 'page' : undefined} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </nav>

      <div className="lg-modebar">
        <span>가계부 말투 · 화면 모드</span>
        <div className="lg-modes" role="group" aria-label="모드 선택">
          {MODES.map((k) => (
            <button key={k} type="button" aria-pressed={mode === k} onClick={() => changeMode(k)}>
              {MODE_LABEL[k]}
            </button>
          ))}
        </div>
      </div>

      {tab === 'summary' && (
        <>
          <Hero mode={mode} ratio={m.ratio} />
          <SummaryTab
            mode={mode} summary={summary} level={level}
            answer={answerFor(mode, current, summary)}
            onPay={(entry) => setEntries((p) => [...p, entry].slice(-24))}
            goHistory={() => setTab('history')}
          />
        </>
      )}

      {tab === 'chat' && (
        <section className="lg-content">
          <div className="lg-panel">
            <h2>가계부에 물어보기</h2>
            <p>
              아래 입력창에서 금액과 항목을 말해 봐. “지난달엔?”, “그럼 1만 원은?”처럼 이어서 물어볼 수도 있어.
            </p>
            <div className="lg-chatlog">
              {entries.length === 0 && <div className="lg-empty">아래 질문창에 물어보거나 예시 버튼을 눌러 봐.</div>}
              {entries.slice(-12).map((e, i) => (
                <div key={i} className="lg-pair">
                  <div className="lg-msg user">{e.text}</div>
                  <div className="lg-msg assistant">
                    <small>{ANSWER_LABEL[mode]}</small>
                    {answerFor(mode, e, summary)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {tab === 'history' && (
        <section className="lg-content">
          <div className="lg-panel">
            <h2>소비 내역</h2>
            <p>월별 소비 내역, 지출 기록, 예산 설정 화면은 다음 단계에서 만들어요.</p>
          </div>
        </section>
      )}

      {tab !== 'history' && (
        <form
          className="lg-chatbar"
          onSubmit={(ev: FormEvent) => {
            ev.preventDefault()
            void ask(question)
          }}
        >
          <div className="lg-quick">
            <button type="button" onClick={() => void ask('오늘 배달 2만 원 시켜도 돼?')}>배달 2만 원?</button>
            <button type="button" onClick={() => void ask('20만 원 결제해도 돼?')}>20만 원 결제?</button>
          </div>
          <div className="lg-chat">
            <label htmlFor="lg-question" aria-label="소비 질문">▤</label>
            <input
              id="lg-question" value={question} placeholder={PLACEHOLDER} autoComplete="off"
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button type="submit" aria-label="질문하기">↗</button>
          </div>
        </form>
      )}
    </div>
  )
}

function Hero({ mode, ratio }: { mode: Mode; ratio: number }) {
  const h = HERO[mode]
  const now = new Date()
  const left = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate() - now.getDate()
  const eyebrow = mode === 'roast' ? `${now.getDate()}일 / 월말까지 ${left}일` : h.eyebrow
  const img = HERO_IMAGE[mode]
  return (
    <section className="lg-hero" style={img ? { backgroundImage: `url('${img}')` } : undefined}>
      <div className="lg-hero-content">
        <span className="eyebrow">{eyebrow}</span>
        <h1>
          {mode === 'roast' ? (
            <>
              {h.title[0]}
              <br />
              <em>{h.title[1]}</em>
            </>
          ) : (
            <>
              {h.title[0]}
              <br />
              {h.title[1]}
            </>
          )}
        </h1>
        <p>{h.sub}</p>
        <span className="badge">{h.badge}</span>
      </div>
      <span className="lg-gridmark" aria-hidden>{ratio}%</span>
    </section>
  )
}

function SummaryTab({
  mode, summary, level, answer, onPay, goHistory,
}: {
  mode: Mode
  summary: Summary
  level: Summary['risk']['level']
  answer: string
  onPay: (e: Entry) => void
  goHistory: () => void
}) {
  const m = metrics(summary)
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('배달')
  const [feedback, setFeedback] = useState<{ blocked: boolean; text: string } | null>(null)
  const planned = summary.balance.planned.find((p) => p.type === 'card_bill') ?? summary.balance.planned[0]
  const day = planned ? Number(planned.dueDate.slice(8)) : null

  async function pay(value: number, cat: string) {
    if (value <= 0) return setFeedback({ blocked: false, text: '금액을 입력해 줘.' })
    try {
      const c = await checkPayment(value, cat, true) // 결제 시도 기록을 남긴다
      setFeedback(paymentFeedback(c))
      onPay({ text: `${cat} ${won(value)} 결제해도 돼?`, intent: 'purchase', amount: value, category: cat, check: c })
    } catch (e) {
      setFeedback({ blocked: true, text: `확인하지 못했어요. (${(e as Error).message})` })
    }
  }

  return (
    <section className="lg-content">
      <div className="lg-answer" role="status" aria-live="polite">
        <small>{ANSWER_LABEL[mode]}</small>
        <span>{answer}</span>
      </div>

      <section className="lg-account">
        <small>대표계좌 · {summary.account ? `${summary.account.bankName} ${summary.account.masked}` : '없음'}</small>
        <strong>{won(m.balance)}</strong>
        <div className="sub">
          <span>{day ? `${day}일 카드대금 반영 후 예상` : '예정 출금 반영 후 예상'}</span>
          <b>{won(m.projected)}</b>
        </div>
      </section>

      <section className="lg-budget">
        <small>이번 달 남은 예산</small>
        <strong>{won(m.remaining)}</strong>
        <div className="lg-progress" role="progressbar" aria-label="월 예산 사용률" aria-valuenow={Math.min(100, m.ratio)} aria-valuemin={0} aria-valuemax={100}>
          <i style={{ width: `${Math.min(100, Math.max(0, m.ratio))}%` }} />
        </div>
        <div className="sub">
          <span>쓴 돈 <b>{won(m.spent)}</b></span>
          <span>월 예산 <b>{won(m.budget)}</b></span>
        </div>
      </section>

      <section className="lg-warning">
        <div className="top">
          <strong>{WARNING_TITLE[mode]}</strong>
          <b>{warningLevelLabel(mode, level)}</b>
        </div>
        <p>{riskText(mode, level, m)}</p>
      </section>

      <section className="lg-reward">
        <b>{REWARD_TITLE[mode]}</b>
        <span>{REWARD_BODY[mode]}</span>
      </section>

      <form className="lg-panel" onSubmit={(e) => { e.preventDefault(); void pay(Number(amount.replace(/[^\d]/g, '')), category) }}>
        <h2>결제 전 확인</h2>
        <div className="lg-fields">
          <label className="lg-field">금액
            <input type="number" min={1} placeholder="예: 20000" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="lg-field">분류
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        </div>
        <button className="lg-action" type="submit">이 금액 결제해도 될까?</button>
        {feedback && <p className={feedback.blocked ? 'lg-feedback blocked' : 'lg-feedback'} role="status" aria-live="polite">{feedback.text}</p>}
      </form>

      <button type="button" className="lg-demopay" onClick={() => void pay(200000, '기타')}>
        20만 원 결제 시뮬레이션 →
      </button>

      <div className="lg-head">
        <h2>지출 흐름</h2>
        <button type="button" onClick={goHistory}>예산·계좌 설정 ›</button>
      </div>
      <div className="lg-panel">
        <div className="lg-muted">
          배달 {won(m.delivery)} / {won(m.deliveryBudget)} ({m.deliveryRatio}%)
        </div>
        {FLOW_CATEGORIES.map((c) => {
          const spent = summary.categories.find((x) => x.category === c)?.spent ?? 0
          const width = Math.min(100, Math.round((spent / Math.max(1, m.spent)) * 100))
          return (
            <div className="lg-line" key={c}>
              <span>{c}</span>
              <div className="lg-minibar"><i style={{ width: `${width}%` }} /></div>
              <b>{won(spent)}</b>
            </div>
          )
        })}
      </div>
    </section>
  )
}
