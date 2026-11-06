import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { won } from '../../format'
import {
  ApiError, addIncome, addTransaction, deleteIncome, deleteTransaction, fetchIncome, fetchOutflows, editTransaction, exportUrl, fetchRecurring, fetchTransactions, fetchTrend,
  registerRecurring, saveBudget, savePlanned, scanReceipt,
  type IncomeItem, type Outflow, type Recurring, type Summary, type TrendMonth, type Tx, type TxList,
} from './api'
import { CATEGORIES } from './copy'
import type { Mode } from './api'

const todayText = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const num = (v: string) => Number(v.replace(/[^\d]/g, '')) || 0

type Section = 'list' | 'analysis' | 'settings'
const SECTIONS: { key: Section; label: string }[] = [
  { key: 'list', label: '내역' },
  { key: 'analysis', label: '분석' },
  { key: 'settings', label: '예산 설정' },
]

type Props = {
  mode: Mode
  summary: Summary
  /** 지출·예산이 바뀌면 요약을 다시 불러온다 */
  reload: () => Promise<void>
}

export default function HistoryTab({ mode, summary, reload }: Props) {
  const [month, setMonth] = useState(todayText().slice(0, 7))
  const [data, setData] = useState<TxList | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    fetchTransactions(month).then(setData).catch((e: Error) => setError(e.message))
  }, [month])

  useEffect(() => {
    setData(null)
    setError(null)
    load()
  }, [load])

  /** 목록과 요약을 같이 갱신 */
  const refresh = async () => {
    load()
    await reload()
  }

  // 소비 내역이 너무 길어지지 않게 네 구역으로 나눈다(주소의 ?s= 로도 바로 열 수 있다)
  const [params, setParams] = useSearchParams()
  const section: Section = SECTIONS.some((x) => x.key === params.get('s')) ? (params.get('s') as Section) : 'list'
  const [adding, setAdding] = useState(false) // ＋ 버튼으로 여는 기록 추가 창
  const [toast, setToast] = useState('')
  useEffect(() => {
    if (!adding) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setAdding(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [adding])
  const go = (k: Section) => setParams(k === 'list' ? {} : { s: k }, { replace: true })

  return (
    <section className="lg-content">
      <nav className="lg-subtabs" aria-label="소비 내역 구역">
        {SECTIONS.map((x) => (
          <button key={x.key} type="button" className={section === x.key ? 'on' : ''} aria-current={section === x.key ? 'true' : undefined} onClick={() => go(x.key)}>{x.label}</button>
        ))}
      </nav>

      {section === 'list' && (
        <>
          <div className="lg-panel">
            <div className="lg-monthhead">
              <h2>월별 소비 내역</h2>
              <label className="lg-field">조회 월
                <input type="month" value={month} max={todayText().slice(0, 7)} onChange={(e) => e.target.value && setMonth(e.target.value)} />
              </label>
            </div>
            {error && <div className="lg-empty">내역을 불러오지 못했어. ({error})</div>}
            {!error && !data && <div className="lg-empty">불러오는 중…</div>}
            {data && (
              <a className="lg-export" href={exportUrl(month)} download>CSV로 내려받기 ↓</a>
            )}
            {data && <Report data={data} mode={mode} dailyLimit={Math.round(summary.budget.total / 30)} onChanged={refresh} />}
          </div>
          <OutflowPanel month={month} version={summary.budget.spent} />
          <IncomePanel month={month} version={summary.income} onChanged={refresh} />
          <div className="lg-fabwrap">
            <button type="button" className="lg-fab" aria-label="지출·수입 기록 추가" onClick={() => setAdding(true)}>＋</button>
          </div>
        </>
      )}

      {section === 'analysis' && (
        <>
          <TrendPanel summary={summary} />
          <RecurringPanel onChanged={refresh} />
        </>
      )}

      {section === 'settings' && <SettingsForm summary={summary} onSaved={refresh} />}

      {adding && (
        <div className="lg-sheet" role="dialog" aria-modal="true" aria-label="기록 추가" onClick={() => setAdding(false)}>
          <div className="body" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="close" aria-label="닫기" onClick={() => setAdding(false)}>✕</button>
            <AddForm summary={summary} onAdded={async (m) => {
              setMonth(m)
              await refresh()
              setAdding(false)
              setToast('기록했어. 내역과 요약을 다시 계산했어.')
              window.setTimeout(() => setToast(''), 3000)
            }} />
          </div>
        </div>
      )}
      {toast && <div className="lg-toast" role="status">{toast}</div>}
    </section>
  )
}

function Report({ data, mode, dailyLimit, onChanged }: { data: TxList; mode: Mode; dailyLimit: number; onChanged: () => Promise<void> }) {
  const { report, items } = data
  const sign = report.delta >= 0 ? '+' : '−'
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null) // 수정 중인 거래 id
  const [day, setDay] = useState<string | null>(null) // 달력에서 고른 날짜. 없으면 한 달 전체
  const [showAll, setShowAll] = useState(false)
  const filtered = day ? items.filter((x) => x.date === day) : items
  const LIMIT = 6
  const shown = showAll || day ? filtered : filtered.slice(0, LIMIT)

  async function remove(id: string) {
    setBusy(id)
    try {
      await deleteTransaction(id)
      await onChanged()
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="lg-report">
        <div>
          <small>총 카드 지출</small>
          <strong>{won(report.spent)}</strong>
          <em>{report.hasPrev ? `전월 대비 ${sign}${won(Math.abs(report.delta))}` : '비교 데이터 없음'}</em>
          {report.income > 0 && <em>수입 {won(report.income)} · 수입 대비 {Math.round((report.spent / report.income) * 100)}%</em>}
        </div>
        <div>
          <small>가장 많이 쓴 항목</small>
          <strong>{report.topCategory ?? '없음'}</strong>
          <em>{report.topCategory ? won(report.topAmount) : '—'}</em>
        </div>
      </div>

      <Calendar month={data.month} items={items} mode={mode} dailyLimit={dailyLimit} day={day} onPick={(d) => setDay((cur) => (cur === d ? null : d))} />

      <div className="lg-listhead">
        <b>{day ? `${Number(day.slice(5, 7))}월 ${Number(day.slice(8))}일 내역` : '이달 전체 내역'}</b>
        {day && <button type="button" onClick={() => setDay(null)}>전체 보기</button>}
      </div>
      <div className="lg-list">
        {shown.length === 0 && <div className="lg-empty">{day ? '이 날은 카드 지출이 없어.' : '이 달의 카드 지출 내역이 없어.'}</div>}
        {shown.map((x) =>
          editing === x.id ? (
            <EditRow key={x.id} tx={x} onDone={async (changed) => { setEditing(null); if (changed) await onChanged() }} />
          ) : (
            <div className="lg-tx" key={x.id}>
              <time>{x.date.slice(5).replace('-', '/')}</time>
              <div>
                <strong>{x.merchant}</strong>
                <small>{x.kind === 'cancel' ? `${x.category} · 취소` : x.category}</small>
              </div>
              <b>{x.amount < 0 ? '−' : '+'}{won(Math.abs(x.amount))}</b>
              <span className="acts">
                {x.canEdit && <button type="button" onClick={() => setEditing(x.id)}>수정</button>}
                {x.canDelete && (
                  <button type="button" disabled={busy === x.id} onClick={() => void remove(x.id)}>
                    삭제
                  </button>
                )}
              </span>
            </div>
          ),
        )}
        {!day && filtered.length > LIMIT && (
          <button type="button" className="lg-more" onClick={() => setShowAll((v) => !v)}>{showAll ? '접기 ▲' : `내역 ${filtered.length - LIMIT}건 더 보기 ▼`}</button>
        )}
      </div>
    </>
  )
}

const WEEK = ['일', '월', '화', '수', '목', '금', '토']

/** 월 달력: 칸마다 그날 쓴 돈(환불은 뺀 순지출)을 적고, 많이 쓴 날일수록 진하게 칠한다. 날짜를 누르면 그날 내역만 본다. */
function Calendar({ month, items, mode, dailyLimit, day, onPick }: { month: string; items: TxList['items']; mode: Mode; dailyLimit: number; day: string | null; onPick: (d: string) => void }) {
  const [y, mo] = month.split('-').map(Number)
  const lead = new Date(y, mo - 1, 1).getDay()
  const days = new Date(y, mo, 0).getDate()
  const spent: Record<string, number> = {}
  for (const x of items) spent[x.date] = (spent[x.date] ?? 0) - x.amount // amount 는 지출이 음수
  const max = Math.max(1, ...Object.values(spent))
  const today = todayText()
  const cells: (number | null)[] = [...Array<null>(lead).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)]
  return (
    <div className="lg-cal" aria-label={`${y}년 ${mo}월 달력`}>
      {WEEK.map((w, i) => <span key={w} className={`wk${i === 0 ? ' sun' : ''}`}>{w}</span>)}
      {cells.map((d, i) => {
        if (d === null) return <i key={`b${i}`} />
        const key = `${month}-${String(d).padStart(2, '0')}`
        const v = spent[key] ?? 0
        const heat = v > 0 ? Math.min(4, Math.ceil((v / max) * 4)) : 0
        return (
          <button key={key} type="button" data-heat={heat} className={`${day === key ? 'sel' : ''}${key === today ? ' today' : ''}`} aria-pressed={day === key} onClick={() => onPick(key)}>
            <em>{d}</em>
            {v > 0 && <small>{mode === 'numbers' ? v.toLocaleString('ko-KR') : v >= 10000 ? `${Math.round(v / 1000) / 10}만` : won(v).replace('원', '')}</small>}
            {mode === 'roast' && v > dailyLimit && <span className="mk" aria-label="하루 예산 초과">🔥</span>}
            {mode === 'kind' && v === 0 && key <= today && <span className="mk" aria-label="무지출">✓</span>}
          </button>
        )
      })}
    </div>
  )
}

/** 한 거래를 그 자리에서 고친다. 분류는 모두, 사용처·금액은 직접 기록한 거래만. */
function EditRow({ tx, onDone }: { tx: Tx; onDone: (changed: boolean) => Promise<void> }) {
  const [category, setCategory] = useState(tx.category)
  const [merchant, setMerchant] = useState(tx.merchant)
  const [amount, setAmount] = useState(String(Math.abs(tx.amount)))
  const [msg, setMsg] = useState('')

  async function save() {
    const patch: { category?: string; merchant?: string; amount?: number } = {}
    if (category !== tx.category) patch.category = category
    if (tx.userMade) {
      if (merchant.trim() && merchant.trim() !== tx.merchant) patch.merchant = merchant.trim()
      const v = num(amount)
      if (v > 0 && v !== Math.abs(tx.amount)) patch.amount = v
    }
    if (Object.keys(patch).length === 0) return void onDone(false)
    try {
      await editTransaction(tx.id, patch)
      await onDone(true)
    } catch (e) {
      const code = e instanceof ApiError ? e.code : ''
      setMsg(code === 'HAS_CANCEL' ? '취소 내역이 있는 거래는 금액을 못 바꿔.' : '수정하지 못했어.')
    }
  }

  return (
    <div className="lg-tx edit">
      <time>{tx.date.slice(5).replace('-', '/')}</time>
      <div className="lg-editfields">
        {tx.userMade ? <input value={merchant} maxLength={30} aria-label="사용처" onChange={(e) => setMerchant(e.target.value)} /> : <strong>{tx.merchant}</strong>}
        <select value={category} aria-label="분류" onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        {tx.userMade && <input type="number" min={1} value={amount} aria-label="금액" onChange={(e) => setAmount(e.target.value)} />}
        {msg && <small>{msg}</small>}
      </div>
      <span className="acts">
        <button type="button" onClick={() => void save()}>저장</button>
        <button type="button" onClick={() => void onDone(false)}>취소</button>
      </span>
    </div>
  )
}

const shortWon = (v: number) => (v >= 10000 ? `${Math.round(v / 1000) / 10}만` : String(v))

/** 분류마다 고정된 색. 모드 색과 상관없이 어느 달이든 같은 분류는 같은 색이다. */
const CAT_COLOR: Record<string, string> = {
  배달: '#ef6a3c', 외식: '#f2b233', 장보기: '#3fae6a', 쇼핑: '#8f6fe0', 교통: '#3b97e3', 생활: '#5f7691', 기타: '#aab3bf',
}
const colorOf = (c: string) => CAT_COLOR[c] ?? '#aab3bf'

/** 최근 6개월 지출 막대. 막대를 누르면 그 달의 분류별 내역과 전달 대비가 아래에 나온다. */
function TrendPanel({ summary }: { summary: Summary }) {
  const [months, setMonths] = useState<TrendMonth[] | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  useEffect(() => {
    fetchTrend(6).then(setMonths).catch(() => setMonths([]))
  }, [summary.budget.spent])
  if (!months || months.length === 0) return null
  const cur = months.find((x) => x.month === picked) ?? months[months.length - 1]
  const idx = months.indexOf(cur)
  const prev = idx > 0 ? months[idx - 1] : null
  const max = Math.max(1, ...months.map((x) => x.spent))
  const entries = Object.entries(cur.byCategory).filter(([, v]) => v > 0).sort((p, q) => q[1] - p[1])
  const diff = prev && prev.spent > 0 ? cur.spent - prev.spent : null
  return (
    <div className="lg-panel">
      <h2>월별 지출 추이</h2>
      <div className="lg-trend2" role="group" aria-label="최근 6개월 월별 지출">
        {months.map((x) => (
          <button key={x.month} type="button" className={x.month === cur.month ? 'col on' : 'col'} aria-pressed={x.month === cur.month} onClick={() => setPicked(x.month)}>
            <small>{x.spent > 0 ? shortWon(x.spent) : '–'}</small>
            <span className="bar" style={{ height: `${Math.max(2, (x.spent / max) * 100)}%` }}>
              {Object.entries(x.byCategory).filter(([, v]) => v > 0).sort((p, q) => q[1] - p[1]).map(([c, v]) => (
                <i key={c} style={{ flexGrow: v, background: colorOf(c) }} />
              ))}
            </span>
            <em>{Number(x.month.slice(5))}월</em>
          </button>
        ))}
      </div>
      <div className="lg-trendinfo">
        <div className="head">
          <b>{Number(cur.month.slice(5))}월 {won(cur.spent)}</b>
          {diff !== null && <span className={diff > 0 ? 'up' : 'down'}>전달보다 {diff > 0 ? '+' : '−'}{won(Math.abs(diff))}</span>}
        </div>
        {entries.length === 0 && <p className="lg-muted">이 달 지출이 없어.</p>}
        {entries.map(([c, v]) => (
          <div className="row" key={c}>
            <span className="dot" style={{ background: colorOf(c) }} />
            <span className="name">{c}</span>
            <span className="meter"><i style={{ width: `${Math.round((v / Math.max(1, cur.spent)) * 100)}%`, background: colorOf(c) }} /></span>
            <b>{won(v)}</b>
            <em>{Math.round((v / Math.max(1, cur.spent)) * 100)}%</em>
          </div>
        ))}
      </div>
    </div>
  )
}

/** 계좌에서 나간 돈(출금·이체). 읽기 전용이고 예산 계산에는 넣지 않는다. */
function OutflowPanel({ month, version }: { month: string; version: number }) {
  const [data, setData] = useState<{ total: number; items: Outflow[] } | null>(null)
  useEffect(() => { fetchOutflows(month).then(setData).catch(() => setData({ total: 0, items: [] })) }, [month, version])
  if (!data || data.items.length === 0) return null
  return (
    <details className="lg-panel lg-collapse">
      <summary><h2>계좌 출금·이체</h2><span>{won(data.total)} · {data.items.length}건</span></summary>
      <p>계좌에서 직접 나간 돈이야. 카드값·대출 상환은 빼고 보여 주고, 예산 계산에는 넣지 않아.</p>
      <div className="lg-list">
        {data.items.map((x) => (
          <div className="lg-tx" key={x.id}>
            <time>{x.date.slice(5).replace('-', '/')}</time>
            <div><strong>{x.to}</strong><small>{x.kind === 'transfer_out' ? '이체' : '출금'} · {x.account}</small></div>
            <b>−{won(x.amount)}</b>
          </div>
        ))}
      </div>
    </details>
  )
}

/** 반복 결제로 보이는 고정지출 후보를 예정 출금에 올린다 */
function RecurringPanel({ onChanged }: { onChanged: () => Promise<void> }) {
  const [items, setItems] = useState<Recurring[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const load = useCallback(() => { fetchRecurring().then(setItems).catch(() => setItems([])) }, [])
  useEffect(load, [load])
  async function add(r: Recurring) {
    setBusy(r.merchant)
    try {
      await registerRecurring({ merchant: r.merchant, amount: r.amount, dueDate: r.nextDate })
      load()
      await onChanged()
    } finally {
      setBusy(null)
    }
  }
  if (!items) return null
  return (
    <details className="lg-panel lg-collapse" open={items.length > 0 && items.length <= 3}>
      <summary><h2>고정지출 후보</h2><span>{items.length}건</span></summary>
      {items.length === 0 && <p>여러 달 반복된 결제가 아직 없어. 거래가 쌓이면 구독·통신비 같은 걸 찾아 줄게.</p>}
      <div className="lg-list">
        {items.map((r) => (
          <div className="lg-tx" key={r.merchant}>
            <time>{r.nextDate.slice(5).replace('-', '/')}</time>
            <div>
              <strong>{r.merchant}</strong>
              <small>{r.category} · {r.months}개월 반복</small>
            </div>
            <b>{won(r.amount)}</b>
            <span className="acts">
              {r.registered ? <small>예정 출금에 등록됨</small> : <button type="button" disabled={busy === r.merchant} onClick={() => void add(r)}>예정 출금에 추가</button>}
            </span>
          </div>
        ))}
      </div>
    </details>
  )
}

/** 그 달에 계좌로 들어온 돈. 가계부에서 기록한 것만 지울 수 있다. */
function IncomePanel({ month, version, onChanged }: { month: string; version: number; onChanged: () => Promise<void> }) {
  const [items, setItems] = useState<IncomeItem[] | null>(null)
  const [msg, setMsg] = useState('')
  const load = useCallback(() => { fetchIncome(month).then(setItems).catch(() => setItems([])) }, [month])
  useEffect(load, [load, version])
  async function remove(id: string) {
    try {
      await deleteIncome(id)
      setMsg('')
      load()
      await onChanged()
    } catch (e) {
      setMsg(e instanceof ApiError && e.code === 'BALANCE_TOO_LOW' ? '지금 잔액이 모자라서 지울 수 없어.' : '지우지 못했어.')
    }
  }
  if (!items) return null
  return (
    <details className="lg-panel lg-collapse">
      <summary><h2>수입 내역</h2><span>{items.length ? `${won(items.reduce((a, x) => a + x.amount, 0))} · ${items.length}건` : '없음'}</span></summary>
      {items.length === 0 && <p>이 달에 들어온 돈이 없어. 아래 기록 칸에서 "수입"으로 넣거나, 물어보기에서 "월급 300만원 들어왔어"라고 해 봐.</p>}
      <div className="lg-list">
        {items.map((x) => (
          <div className="lg-tx" key={x.id}>
            <time>{x.date.slice(5).replace('-', '/')}</time>
            <div><strong>{x.source}</strong></div>
            <b className="in">+{won(x.amount)}</b>
            {x.canDelete && <span className="acts"><button type="button" onClick={() => void remove(x.id)}>삭제</button></span>}
          </div>
        ))}
      </div>
      {msg && <p className="lg-feedback" role="status">{msg}</p>}
    </details>
  )
}

function AddForm({ summary, onAdded }: { summary: Summary; onAdded: (month: string) => Promise<void> }) {
  const [date, setDate] = useState(todayText())
  const [category, setCategory] = useState('배달')
  const [merchant, setMerchant] = useState('')
  const [amount, setAmount] = useState('')
  const [msg, setMsg] = useState('')
  const [kind, setKind] = useState<'expense' | 'income'>('expense')
  const [scanning, setScanning] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  /** 영수증 사진을 읽어 입력 칸을 채운다. 저장은 사용자가 확인하고 직접 누른다. */
  async function scan(file: File | undefined) {
    if (!file) return
    if (file.size > 5_000_000) return setMsg('사진이 너무 커. 5MB 이하로 올려 줘.')
    setScanning(true)
    setMsg('영수증을 읽는 중이야…')
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader()
        r.onload = () => resolve(String(r.result).split(',')[1] ?? '')
        r.onerror = () => reject(new Error('read'))
        r.readAsDataURL(file)
      })
      const f = await scanReceipt(b64, file.type)
      if (f.merchant) setMerchant(f.merchant)
      if (f.amount) setAmount(String(f.amount))
      setDate(f.date)
      setCategory(f.category)
      setMsg(f.amount ? '읽어서 채웠어. 맞는지 확인하고 "지출 기록 추가"를 눌러 줘.' : '금액을 못 읽었어. 직접 입력해 줘.')
    } catch (e) {
      const code = e instanceof ApiError ? e.code : ''
      setMsg(code === 'OCR_UNAVAILABLE' ? '지금은 영수증을 읽을 수 없어. 직접 입력해 줘.' : '영수증을 읽지 못했어. 직접 입력해 줘.')
    } finally {
      setScanning(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const value = num(amount)
    if (value <= 0 || !merchant.trim() || !date) return setMsg(kind === 'income' ? '날짜, 수입 이름, 금액을 입력해 줘.' : '날짜, 사용처, 금액을 입력해 줘.')
    if (date > todayText()) return setMsg('미래 날짜는 기록할 수 없어.')
    try {
      if (kind === 'income') {
        await addIncome({ date, source: merchant.trim(), amount: value })
        setMsg(`수입 ${won(value)}을 기록했어. 계좌 잔액과 예상 잔액이 늘었어.`)
      } else {
        await addTransaction({ date, merchant: merchant.trim(), category, amount: value })
        setMsg(`${won(value)} 기록했어. 이번 달 예산과 예상 잔액을 다시 계산했어.`)
      }
      setMerchant('')
      setAmount('')
      setDate(todayText())
      await onAdded(date.slice(0, 7))
    } catch (err) {
      const code = err instanceof ApiError ? err.code : ''
      setMsg(
        code === 'FUTURE_DATE' ? '미래 날짜는 기록할 수 없어.'
        : code === 'NO_ACTIVE_CARD' ? '사용 중인 카드가 없어서 기록할 수 없어.'
        : '기록하지 못했어. 잠시 후 다시 해 줘.',
      )
    }
  }

  return (
    <form className="lg-panel" onSubmit={(e) => void submit(e)}>
      <div className="lg-kind" role="group" aria-label="기록 종류">
        <button type="button" aria-pressed={kind === 'expense'} onClick={() => setKind('expense')}>지출</button>
        <button type="button" aria-pressed={kind === 'income'} onClick={() => setKind('income')}>수입</button>
      </div>
      <div className="lg-panelhead">
        <h2>{kind === 'income' ? '수입 기록' : '카드 지출 기록'}</h2>
        {kind === 'expense' && <button type="button" className="lg-newchat" disabled={scanning} onClick={() => fileRef.current?.click()}>📷 영수증</button>}
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => void scan(e.target.files?.[0])} />
      </div>
      <div className="lg-fields">
        <label className="lg-field">날짜
          <input type="date" value={date} max={todayText()} required onChange={(e) => setDate(e.target.value)} />
        </label>
        {kind === 'expense' && (
          <label className="lg-field">분류
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        )}
        <label className={kind === 'expense' ? 'lg-field wide' : 'lg-field'}>{kind === 'income' ? '수입 이름' : '사용처'}
          <input value={merchant} maxLength={30} placeholder={kind === 'income' ? '예: 월급, 용돈' : '예: 점심 배달'} required onChange={(e) => setMerchant(e.target.value)} />
        </label>
        <label className="lg-field wide">금액
          <input type="number" min={1} step={1} value={amount} placeholder={`예: ${summary.examples.typical}`} required onChange={(e) => setAmount(e.target.value)} />
        </label>
      </div>
      <button className="lg-action" type="submit">{kind === 'income' ? '수입 기록 추가' : '지출 기록 추가'}</button>
      {msg && <p className="lg-feedback" role="status" aria-live="polite">{msg}</p>}
    </form>
  )
}

function SettingsForm({ summary, onSaved }: { summary: Summary; onSaved: () => Promise<void> }) {
  const bill = summary.balance.planned.find((p) => p.type === 'card_bill')
  const fromSummary = () => Object.fromEntries(CATEGORIES.map((c) => [c, String(summary.categories.find((x) => x.category === c)?.budget ?? '')]))
  const [total, setTotal] = useState(String(summary.budget.total || ''))
  const [cats, setCats] = useState<Record<string, string>>(fromSummary)
  const [billAmount, setBillAmount] = useState(String(bill?.amount ?? ''))
  const [msg, setMsg] = useState('')

  // 다른 곳(지출 기록 등)에서 값이 바뀌면 입력칸도 맞춘다
  const catKey = summary.categories.map((c) => `${c.category}:${c.budget ?? ''}`).join('|')
  useEffect(() => {
    setTotal(String(summary.budget.total || ''))
    setCats(fromSummary())
    setBillAmount(String(bill?.amount ?? ''))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary.budget.total, catKey, bill?.amount])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const t = num(total)
    if (t < 1) return setMsg('월 예산은 1원 이상 입력해 줘.')
    const set: Record<string, number> = {}
    const clear: string[] = []
    for (const c of CATEGORIES) {
      const v = num(cats[c] ?? '')
      if (v > 0) set[c] = v
      else clear.push(c) // 비워 두면 그 분류 예산은 설정하지 않는다
    }
    if (Object.values(set).reduce((a, b) => a + b, 0) > t) return setMsg('분류 예산의 합이 월 예산보다 커. 확인해 줘.')
    try {
      await saveBudget(t, set, clear)
      if (bill) await savePlanned(bill.id, num(billAmount))
      setMsg('설정을 저장했어. 월 예산과 경고를 다시 계산했어.')
      await onSaved()
    } catch {
      setMsg('저장하지 못했어. 잠시 후 다시 해 줘.')
    }
  }

  return (
    <form className="lg-panel" id="lg-settings" onSubmit={(e) => void submit(e)}>
      <h2>예산·계좌 설정</h2>
      <div className="lg-fields">
        <label className="lg-field">월 예산
          <input type="number" min={1} required value={total} onChange={(e) => setTotal(e.target.value)} />
        </label>
        <label className="lg-field">예정 카드대금
          <input type="number" min={0} value={billAmount} disabled={!bill} onChange={(e) => setBillAmount(e.target.value)} />
        </label>
        <div className="lg-field wide">대표계좌 잔액
          <div className="lg-readonly">{won(summary.balance.current)}</div>
        </div>
      </div>
      <h3 className="lg-subhead">분류별 예산 <small>비워 두면 설정 안 함</small></h3>
      <div className="lg-fields">
        {CATEGORIES.map((c) => (
          <label className="lg-field" key={c}>{c} 예산
            <input type="number" min={1} placeholder="없음" value={cats[c] ?? ''} onChange={(e) => setCats((p) => ({ ...p, [c]: e.target.value }))} />
          </label>
        ))}
      </div>
      <p className="lg-note">
        계좌 잔액은 계좌 서비스에서 가져와. 직접 바꿀 수는 없고, 수입을 기록하면 그만큼 늘어나. 카드값 반영 후 예상은{' '}
        <b>{won(summary.balance.expected)}</b>이고, 이번 달 카드 지출을 기록하면 카드대금이 늘어난 만큼 줄어들어.
      </p>
      <button className="lg-action" type="submit">설정 저장</button>
      {msg && <p className="lg-feedback" role="status" aria-live="polite">{msg}</p>}
    </form>
  )
}
