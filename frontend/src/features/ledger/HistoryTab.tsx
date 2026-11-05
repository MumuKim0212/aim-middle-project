import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { won } from '../../format'
import {
  ApiError, addTransaction, deleteTransaction, fetchTransactions, saveBudget, savePlanned,
  type Summary, type TxList,
} from './api'
import { CATEGORIES } from './copy'

const todayText = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const num = (v: string) => Number(v.replace(/[^\d]/g, '')) || 0

type Props = {
  summary: Summary
  /** 지출·예산이 바뀌면 요약을 다시 불러온다 */
  reload: () => Promise<void>
}

export default function HistoryTab({ summary, reload }: Props) {
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

  return (
    <section className="lg-content">
      <div className="lg-panel">
        <div className="lg-monthhead">
          <h2>월별 소비 내역</h2>
          <label className="lg-field">조회 월
            <input type="month" value={month} max={todayText().slice(0, 7)} onChange={(e) => e.target.value && setMonth(e.target.value)} />
          </label>
        </div>
        {error && <div className="lg-empty">내역을 불러오지 못했어. ({error})</div>}
        {!error && !data && <div className="lg-empty">불러오는 중…</div>}
        {data && <Report data={data} onChanged={refresh} />}
      </div>

      <AddForm summary={summary} onAdded={async (m) => { setMonth(m); await refresh() }} />
      <SettingsForm summary={summary} onSaved={refresh} />
    </section>
  )
}

function Report({ data, onChanged }: { data: TxList; onChanged: () => Promise<void> }) {
  const { report, items } = data
  const sign = report.delta >= 0 ? '+' : '−'
  const [busy, setBusy] = useState<string | null>(null)

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
        </div>
        <div>
          <small>가장 많이 쓴 항목</small>
          <strong>{report.topCategory ?? '없음'}</strong>
          <em>{report.topCategory ? won(report.topAmount) : '—'}</em>
        </div>
      </div>

      <div className="lg-list">
        {items.length === 0 && <div className="lg-empty">이 달의 카드 지출 내역이 없어.</div>}
        {items.map((x) => (
          <div className="lg-tx" key={x.id}>
            <time>{x.date.slice(5).replace('-', '/')}</time>
            <div>
              <strong>{x.merchant}</strong>
              <small>{x.kind === 'cancel' ? `${x.category} · 취소` : x.category}</small>
            </div>
            <b>{x.amount < 0 ? '−' : '+'}{won(Math.abs(x.amount))}</b>
            {x.canDelete && (
              <button type="button" disabled={busy === x.id} onClick={() => void remove(x.id)}>
                삭제
              </button>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

function AddForm({ summary, onAdded }: { summary: Summary; onAdded: (month: string) => Promise<void> }) {
  const [date, setDate] = useState(todayText())
  const [category, setCategory] = useState('배달')
  const [merchant, setMerchant] = useState('')
  const [amount, setAmount] = useState('')
  const [msg, setMsg] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    const value = num(amount)
    if (value <= 0 || !merchant.trim() || !date) return setMsg('날짜, 사용처, 금액을 입력해 줘.')
    if (date > todayText()) return setMsg('미래 날짜는 지출 내역으로 기록할 수 없어.')
    try {
      await addTransaction({ date, merchant: merchant.trim(), category, amount: value })
      setMsg(`${won(value)} 기록했어. 이번 달 예산과 예상 잔액을 다시 계산했어.`)
      setMerchant('')
      setAmount('')
      setDate(todayText())
      await onAdded(date.slice(0, 7))
    } catch (err) {
      const code = err instanceof ApiError ? err.code : ''
      setMsg(
        code === 'FUTURE_DATE' ? '미래 날짜는 지출 내역으로 기록할 수 없어.'
        : code === 'NO_ACTIVE_CARD' ? '사용 중인 카드가 없어서 기록할 수 없어.'
        : '기록하지 못했어. 잠시 후 다시 해 줘.',
      )
    }
  }

  return (
    <form className="lg-panel" onSubmit={(e) => void submit(e)}>
      <h2>카드 지출 기록</h2>
      <div className="lg-fields">
        <label className="lg-field">날짜
          <input type="date" value={date} max={todayText()} required onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="lg-field">분류
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="lg-field wide">사용처
          <input value={merchant} maxLength={30} placeholder="예: 점심 배달" required onChange={(e) => setMerchant(e.target.value)} />
        </label>
        <label className="lg-field wide">금액
          <input type="number" min={1} step={1} value={amount} placeholder={`예: ${summary.examples.typical}`} required onChange={(e) => setAmount(e.target.value)} />
        </label>
      </div>
      <button className="lg-action" type="submit">지출 기록 추가</button>
      {msg && <p className="lg-feedback" role="status" aria-live="polite">{msg}</p>}
    </form>
  )
}

function SettingsForm({ summary, onSaved }: { summary: Summary; onSaved: () => Promise<void> }) {
  const delivery = summary.categories.find((c) => c.category === '배달')
  const bill = summary.balance.planned.find((p) => p.type === 'card_bill')
  const [total, setTotal] = useState(String(summary.budget.total || ''))
  const [deliveryBudget, setDeliveryBudget] = useState(String(delivery?.budget ?? ''))
  const [billAmount, setBillAmount] = useState(String(bill?.amount ?? ''))
  const [msg, setMsg] = useState('')

  // 다른 곳(지출 기록 등)에서 값이 바뀌면 입력칸도 맞춘다
  useEffect(() => {
    setTotal(String(summary.budget.total || ''))
    setDeliveryBudget(String(delivery?.budget ?? ''))
    setBillAmount(String(bill?.amount ?? ''))
  }, [summary.budget.total, delivery?.budget, bill?.amount])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const t = num(total), d = num(deliveryBudget)
    if (t < 1 || d < 1) return setMsg('예산은 1원 이상 입력해 줘.')
    try {
      await saveBudget(t, { 배달: d })
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
        <label className="lg-field">배달 예산
          <input type="number" min={1} required value={deliveryBudget} onChange={(e) => setDeliveryBudget(e.target.value)} />
        </label>
        <label className="lg-field">예정 카드대금
          <input type="number" min={0} value={billAmount} disabled={!bill} onChange={(e) => setBillAmount(e.target.value)} />
        </label>
        <div className="lg-field">대표계좌 잔액
          <div className="lg-readonly">{won(summary.balance.current)}</div>
        </div>
      </div>
      <p className="lg-note">
        계좌 잔액은 계좌 서비스에서 가져와서 여기서는 바꿀 수 없어. 카드값 반영 후 예상은{' '}
        <b>{won(summary.balance.expected)}</b>이고, 이번 달 카드 지출을 기록하면 카드대금이 늘어난 만큼 줄어들어.
      </p>
      <button className="lg-action" type="submit">설정 저장</button>
      {msg && <p className="lg-feedback" role="status" aria-live="polite">{msg}</p>}
    </form>
  )
}
