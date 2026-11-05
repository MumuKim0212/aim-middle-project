import { useEffect, useRef, useState, type FormEvent } from 'react'
import { won } from '../../format'
import { checkPayment, fetchChat, fetchSettings, fetchSummary, newChat, saveSettings, streamChat, type Mode, type Summary } from './api'
import AnswerCard from './AnswerCard'
import HistoryTab from './HistoryTab'
import {
  ANSWER_LABEL, CATEGORIES, HERO, MODE_LABEL, MODES, REWARD_TITLE, STAT_LABEL, WARNING_TITLE,
  answerFor, forecastText, metrics, paymentFeedback, rewardBody, riskText, warningLevelLabel, type Entry,
} from './copy'
import './ledger.css'

type Tab = 'summary' | 'chat' | 'history'
const TABS: { key: Tab; label: string }[] = [
  { key: 'summary', label: '요약' },
  { key: 'chat', label: '물어보기' },
  { key: 'history', label: '소비 내역' },
]
/** 예시 질문. 금액은 DB 에서 계산한 평소 배달 금액을 쓴다. */
const sampleText = (s: Summary) => `오늘 ${s.examples.category} ${won(s.examples.typical)} 시켜도 돼?`
const HERO_IMAGE: Partial<Record<Mode, string>> = {
  roast: '/ledger/hell-gate.webp',
  basic: '/ledger/bank-glass.webp',
  kind: '/ledger/cute-pig.webp',
}
const FLOW_CATEGORIES = ['배달', '쇼핑', '생활', '장보기']
const ROAST_LEVELS = [
  { v: 1, label: '순한맛' },
  { v: 2, label: '보통' },
  { v: 3, label: '매운맛' },
]

/** 답변을 만들어 보여 주는 중인 질문. target 은 서버에서 받은 글자, shown 은 화면에 풀어 놓은 만큼이다. */
type Live = { question: string; mode: Mode; target: string; shown: string; final: Entry | null }

/**
 * 라벨과 문장은 항상 "지금 선택한 모드" 기준이다.
 * 그 모드로 쓴 LLM 답변이 있으면 그것을, 없으면(다른 모드로 물어봤던 질문 등) 그 모드의 템플릿 문장을 쓴다.
 */
function answerOf(mode: Mode, e: Entry, s: Summary): { label: string; text: string } {
  const llm = e.answers?.[mode]?.text
  return { label: ANSWER_LABEL[mode], text: llm ?? answerFor(mode, e, s) }
}

export default function LedgerPage() {
  const [mode, setModeState] = useState<Mode>('roast')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [initial, setInitial] = useState<Entry | null>(null)
  const [chats, setChats] = useState<Partial<Record<Mode, Entry[]>>>({}) // 모드마다 대화가 따로다
  const [tab, setTab] = useState<Tab>('summary')
  const [question, setQuestion] = useState('')
  const [roastLevel, setRoastLevel] = useState(2) // 싸가지 모드 욕설 강도
  const [live, setLive] = useState<Live | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetchSummary()
      .then(async (s) => {
        const ex = s.examples
        const [st, chk, chat] = await Promise.all([fetchSettings(), checkPayment(ex.typical, ex.category, false), fetchSettings().then((x) => fetchChat(x.mode))])
        setSummary(s)
        setModeState(st.mode)
        setRoastLevel(st.roastLevel)
        setChats({ [st.mode]: chat }) // 저장된 대화를 이어서 보여준다
        setInitial({ text: sampleText(s), intent: 'purchase', amount: ex.typical, category: ex.category, check: chk })
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const entries = chats[mode] ?? []
  const addEntry = (md: Mode, e: Entry) => setChats((p) => ({ ...p, [md]: [...(p[md] ?? []), e].slice(-24) }))

  // 모드를 바꾸면 그 모드의 대화를 불러온다(한 번 불러온 모드는 다시 부르지 않는다)
  useEffect(() => {
    if (chats[mode]) return
    let alive = true
    fetchChat(mode).then((c) => alive && setChats((p) => ({ ...p, [mode]: c }))).catch(() => alive && setChats((p) => ({ ...p, [mode]: [] })))
    return () => { alive = false }
  }, [mode, chats])

  // 물어보기 탭에서 새 답변이 생기면 맨 아래(채팅바 위)로 스크롤한다
  const liveActive = live !== null
  const shownLen = live?.shown.length ?? 0
  useEffect(() => {
    if (tab !== 'chat') return
    document.querySelector('.lg-pair:last-child')?.scrollIntoView({ behavior: liveActive ? 'auto' : 'smooth', block: 'end' })
  }, [tab, entries.length, liveActive, shownLen])

  // 답변이 끝나면 입력창으로 포커스를 돌려준다(바로 다음 질문을 칠 수 있게)
  useEffect(() => {
    if (!liveActive) inputRef.current?.focus({ preventScroll: true })
  }, [liveActive])

  // 받은 글자를 일정한 속도로 풀어서 보여 준다. Gemini 는 문장 덩어리로 보내서 그대로 찍으면 뚝뚝 끊긴다.
  useEffect(() => {
    if (!liveActive) return
    const id = window.setInterval(() => {
      setLive((l) => {
        if (!l || l.shown.length >= l.target.length) return l
        const step = Math.max(1, Math.ceil((l.target.length - l.shown.length) / 14)) // 밀린 만큼 조금씩 빠르게 따라잡는다
        return { ...l, shown: l.target.slice(0, l.shown.length + step) }
      })
    }, 30)
    return () => window.clearInterval(id)
  }, [liveActive])

  // 끝까지 보여 줬으면 확정된 대화로 옮긴다(답변이 없으면 바로 옮겨서 템플릿 문장을 보여 준다)
  useEffect(() => {
    if (!live?.final) return
    if (live.final.answers?.[live.mode] && live.shown.length < live.target.length) return
    const entry = live.final
    addEntry(live.mode, entry)
    setLive(null)
  }, [live])

  /** 지출·예산이 바뀐 뒤 요약(남은 예산, 예상 잔액, 경고)을 다시 불러온다 */
  const reloadSummary = async () => {
    const s = await fetchSummary()
    const chk = await checkPayment(s.examples.typical, s.examples.category, false)
    setSummary(s)
    setInitial({ text: sampleText(s), intent: 'purchase', amount: s.examples.typical, category: s.examples.category, check: chk }) // 첫 답변도 새 수치로 다시 판정
  }

  const changeMode = (md: Mode) => {
    if (live) return // 답변을 만드는 중에는 모드를 바꾸지 않는다(답변이 엉뚱한 모드 대화에 붙지 않게)
    setModeState(md)
    saveSettings({ mode: md }).catch(() => undefined) // 저장 실패해도 화면 전환은 유지
  }

  /** 이 모드의 대화를 비우고 새로 시작한다(다른 모드의 대화는 그대로) */
  const startNewChat = () => {
    if (live) return
    newChat(mode).then(() => setChats((p) => ({ ...p, [mode]: [] }))).catch((e: Error) => setError(e.message))
  }

  const changeLevel = (v: number) => {
    setRoastLevel(v)
    saveSettings({ roastLevel: v }).catch(() => undefined)
  }

  /** 질문은 서버가 해석·계산하고, 답변은 스트림으로 받아 대화로 저장된다. */
  async function ask(raw: string, opts?: { stay?: boolean }) {
    const text = raw.trim() || (summary ? sampleText(summary) : '')
    if (!text || live) return // 앞 질문의 답변을 만드는 중이면 기다린다
    if (tab === 'summary' && !opts?.stay) setTab('chat') // 요약에서 물어보면 대화가 보이는 물어보기 탭으로 간다
    setLive({ question: text, mode, target: '', shown: '', final: null })
    setQuestion('')
    try {
      await streamChat(text, mode, roastLevel, {
        onDelta: (t) => setLive((l) => (l ? { ...l, target: l.target + t } : l)),
        onReset: () => setLive((l) => (l ? { ...l, target: '', shown: '' } : l)), // 다시 쓰는 중: 스피너로 돌아간다
        onDone: (entry) => {
          setLive((l) => (l ? { ...l, final: entry } : l))
          if (entry.recorded) void reloadSummary().catch(() => undefined) // 대화로 지출을 기록했으면 요약 숫자도 새로
        },
      })
    } catch (e) {
      setLive(null)
      setError((e as Error).message)
    }
  }

  if (error) {
    return (
      <div className="state">
        <p>데이터를 불러오지 못했어요.</p>
        <small>{error} · 백엔드가 켜져 있는지 확인하세요.</small>
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
            <button key={k} type="button" aria-pressed={mode === k} disabled={!!live} onClick={() => changeMode(k)}>
              {MODE_LABEL[k]}
            </button>
          ))}
        </div>
        {mode === 'roast' && (
          <div className="lg-level" role="group" aria-label="욕설 강도">
            <span>욕설 강도</span>
            {ROAST_LEVELS.map((l) => (
              <button key={l.v} type="button" aria-pressed={roastLevel === l.v} onClick={() => changeLevel(l.v)}>
                {l.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {tab === 'summary' && (
        <>
          <Hero mode={mode} ratio={m.ratio} />
          <SummaryTab
            mode={mode} summary={summary} level={level}
            answer={live ? { label: ANSWER_LABEL[mode], text: live.shown, busy: true, typing: live.shown !== '' } : { ...answerOf(mode, current, summary), busy: false, typing: false }}
            onAsked={ask}
            goHistory={() => setTab('history')}
          />
        </>
      )}

      {tab === 'chat' && (
        <section className="lg-content">
          <div className="lg-panel">
            <div className="lg-panelhead">
              <h2>가계부에 물어보기</h2>
              <button type="button" className="lg-newchat" disabled={!!live || entries.length === 0} onClick={startNewChat}>＋ 새 대화</button>
            </div>
            <p>
              아래 입력창에서 금액과 항목을 말해 봐. “지난달엔?”, “그럼 1만 원은?”처럼 이어서 물어볼 수도 있어.
            </p>
            <div className="lg-chatlog">
              {entries.length === 0 && !live && <div className="lg-empty">아래 질문창에 물어보거나 예시 버튼을 눌러 봐.</div>}
              {entries.slice(-12).map((e, i) => {
                const a = answerOf(mode, e, summary)
                return (
                  <div key={i} className="lg-pair">
                    <div className="lg-msg user">{e.text}</div>
                    <div className="lg-msg assistant">
                      <small>{a.label}</small>
                      <AnswerCard entry={e} summary={summary} text={a.text} />
                    </div>
                  </div>
                )
              })}
              {live && (
                <div className="lg-pair">
                  <div className="lg-msg user">{live.question}</div>
                  <div className="lg-msg assistant" aria-live="polite">
                    <small>{ANSWER_LABEL[mode]}</small>
                    {live.shown === '' ? <Thinking /> : <>{live.shown}<i className="lg-caret" aria-hidden /></>}
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {tab === 'history' && (
        <HistoryTab mode={mode} summary={summary} reload={reloadSummary} />
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
            <button type="button" disabled={!!live} onClick={() => void ask(sampleText(summary))}>{summary.examples.category} {won(summary.examples.typical)}?</button>
            <button type="button" disabled={!!live} onClick={() => void ask(`${won(summary.examples.large)} 결제해도 돼?`)}>{won(summary.examples.large)} 결제?</button>
          </div>
          <div className="lg-chat">
            <label htmlFor="lg-question" aria-label="소비 질문">▤</label>
            <input
              id="lg-question" ref={inputRef} value={question} placeholder={sampleText(summary)} autoComplete="off" readOnly={!!live}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button type="submit" aria-label="질문하기" disabled={!!live}>↗</button>
          </div>
        </form>
      )}
    </div>
  )
}

/** 답변을 기다리는 동안: 도는 스피너 + 반짝이는 문구 */
function Thinking() {
  return (
    <span className="lg-thinking" role="status">
      <i className="lg-spinner" aria-hidden />
      <span className="lg-shimmer">생각 중…</span>
    </span>
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
  mode, summary, level, answer, onAsked, goHistory,
}: {
  mode: Mode
  summary: Summary
  level: Summary['risk']['level']
  answer: { label: string; text: string; busy: boolean; typing: boolean }
  onAsked: (text: string, opts?: { stay?: boolean }) => Promise<void>
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
      await onAsked(`${cat} ${won(value)} 결제해도 돼?`, { stay: true }) // 같은 질문을 대화에도 남기되, 폼의 결과를 보고 있으니 탭은 옮기지 않는다
    } catch (e) {
      setFeedback({ blocked: true, text: `확인하지 못했어요. (${(e as Error).message})` })
    }
  }

  const rewardBlock = (
    <div className="lg-reward">
      <b>{REWARD_TITLE[mode]}</b>
      <span>{rewardBody(mode, summary.examples.typical)}</span>
    </div>
  )

  return (
    <section className="lg-content lg-summary">
      <div className="lg-answer" role="status" aria-live="polite">
        <small>{answer.label}</small>
        {answer.busy && !answer.typing ? <Thinking /> : <span>{answer.text}{answer.busy && <i className="lg-caret" aria-hidden />}</span>}
      </div>

      {mode === 'numbers' && <NumbersTable summary={summary} />}

      {mode === 'kind' && <section className="lg-cheer">{rewardBlock}</section>}

      <Alerts summary={summary} />

      <div className="lg-duo">
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
      </div>

      <section className="lg-insight">
        {summary.forecast && forecastText(mode, summary.forecast, m.budget) && (
          <p className="lg-forecast">{forecastText(mode, summary.forecast, m.budget)}</p>
        )}
        <div className="lg-chips">
          <span><small>{STAT_LABEL[mode].streak}</small><b>{summary.streak}일</b></span>
          <span><small>{STAT_LABEL[mode].saved}</small><b>{won(summary.saved.heldAmount)}</b><i>{summary.saved.heldCount}번</i></span>
        </div>
      </section>

      <section className="lg-warning">
        <div className="top">
          <strong>{WARNING_TITLE[mode]}</strong>
          <b>{warningLevelLabel(mode, level)}</b>
        </div>
        <p>{riskText(mode, level, m)}</p>
        {mode !== 'kind' && rewardBlock}
      </section>

      <details className="lg-fold" key={mode}>
      <summary><span>결제 전 확인</span> <small>금액 넣고 확인</small></summary>
      <form className="lg-panel" onSubmit={(e) => { e.preventDefault(); void pay(Number(amount.replace(/[^\d]/g, '')), category) }}>
        <div className="lg-fields">
          <label className="lg-field">금액
            <input type="number" min={1} placeholder={`예: ${summary.examples.typical}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
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

      <button type="button" className="lg-demopay" onClick={() => void pay(summary.examples.large, '기타')}>
        {won(summary.examples.large)} 결제 시뮬레이션 →
      </button>
      </details>

      <div className="lg-flow">
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
      </div>
    </section>
  )
}

/** 예산·카드대금 알림. 서버 요약에서 바로 계산한다(80% 도달, 예산 초과, 카드대금 3일 이내). */
function Alerts({ summary: s }: { summary: Summary }) {
  const items: { key: string; text: string; tone: 'warn' | 'bad' }[] = []
  if (s.budget.set) {
    if (s.budget.remaining <= 0) items.push({ key: 'over', text: '이번 달 월 예산을 모두 썼어요.', tone: 'bad' })
    else if (s.budget.ratio >= 80) items.push({ key: 'eighty', text: `월 예산의 ${s.budget.ratio}%를 썼어요.`, tone: 'warn' })
  }
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  for (const p of s.balance.planned) {
    const d = Math.round((new Date(p.dueDate + 'T00:00:00').getTime() - today.getTime()) / 86_400_000)
    if (d >= 0 && d <= 3) items.push({ key: p.id, text: `${p.type === 'card_bill' ? '카드대금' : '예정 출금'} ${won(p.amount)}이 ${d === 0 ? '오늘' : `${d}일 뒤`} 나가요.`, tone: 'warn' })
  }
  if (items.length === 0) return null
  return (
    <div className="lg-alerts" role="status">
      {items.map((i) => <p key={i.key} className={i.tone}>{i.text}</p>)}
    </div>
  )
}

/** 숫자만 모드: 카드 대신 한 장의 표로 모아 보여 준다 */
function NumbersTable({ summary: s }: { summary: Summary }) {
  const m = metrics(s)
  const rows: [string, string][] = [
    ['계좌 잔액', won(m.balance)],
    ['카드대금 반영 후 예상', won(m.projected)],
    ['월 예산', won(m.budget)],
    ['쓴 돈', `${won(m.spent)} (${m.ratio}%)`],
    ['남은 예산', won(m.remaining)],
    ['배달 지출 / 예산', `${won(m.delivery)} / ${won(m.deliveryBudget)} (${m.deliveryRatio}%)`],
  ]
  return (
    <table className="lg-ntable">
      <tbody>
        {rows.map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}
      </tbody>
    </table>
  )
}
