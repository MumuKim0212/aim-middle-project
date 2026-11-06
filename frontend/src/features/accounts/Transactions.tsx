import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { won } from '../../format'
import { callJson } from '../../lib/http'
import type { Tx } from './api'
import { errMsg } from './api'

type Page = { items: Tx[]; hasNext: boolean }
const PERIODS = [['1w', '1주'], ['1m', '1개월'], ['3m', '3개월'], ['custom', '직접 입력']] as const
const TYPES = [['all', '전체'], ['deposit', '입금'], ['withdraw', '출금']] as const
const today = () => new Date().toLocaleDateString('sv-SE') // YYYY-MM-DD (로컬 날짜)
const fmt = (iso: string) => iso.slice(0, 16).replace('T', ' ').replace(/-/g, '.')

/** A-05 거래 내역: 기간·입금/출금 필터, 최신순, 20건씩 더 보기. 거래 후 잔액을 함께 보여 준다. */
export default function Transactions() {
  const id = useParams().id
  const [period, setPeriod] = useState<(typeof PERIODS)[number][0]>('1m')
  const [type, setType] = useState<(typeof TYPES)[number][0]>('all')
  const [from, setFrom] = useState(today())
  const [to, setTo] = useState(today())
  const [rows, setRows] = useState<Tx[]>([])
  const [page, setPage] = useState(1)
  const [more, setMore] = useState(false)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const query = `period=${period}&type=${type}${period === 'custom' ? `&from=${from}&to=${to}` : ''}`
  // 필터가 바뀌면 1페이지부터 다시 읽는다
  useEffect(() => {
    let alive = true
    setState('loading'); setErr(null)
    callJson<Page & { page: number }>('GET', `/api/accounts/${id}/transactions?${query}&page=1`)
      .then((d) => { if (alive) { setRows(d.items); setPage(1); setMore(d.hasNext); setState('ready') } })
      .catch((e) => { if (alive) { setErr(errMsg(e)); setState('error') } })
    return () => { alive = false }
  }, [id, query, tick])

  async function loadMore() {
    try {
      const d = await callJson<Page>('GET', `/api/accounts/${id}/transactions?${query}&page=${page + 1}`)
      setRows((r) => [...r, ...d.items]); setPage(page + 1); setMore(d.hasNext)
    } catch (e) { setErr(errMsg(e)) }
  }

  return (
    <section className="ac-page">
      <h2 className="auth-title">거래 내역</h2>
      <div className="chips" role="group" aria-label="기간">{PERIODS.map(([k, l]) => <button key={k} type="button" className={period === k ? 'chip on' : 'chip'} onClick={() => setPeriod(k)}>{l}</button>)}</div>
      {period === 'custom' && (
        <div className="ac-dates">
          <input type="date" aria-label="시작일" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          <span>~</span>
          <input type="date" aria-label="종료일" value={to} min={from} max={today()} onChange={(e) => setTo(e.target.value)} />
        </div>
      )}
      <div className="chips" role="group" aria-label="유형">{TYPES.map(([k, l]) => <button key={k} type="button" className={type === k ? 'chip on' : 'chip'} onClick={() => setType(k)}>{l}</button>)}</div>

      {state === 'loading' && <div className="state">불러오는 중…</div>}
      {state === 'error' && <div className="state">{err}<br /><button type="button" className="ac-retry" onClick={() => setTick((n) => n + 1)}>다시 시도</button></div>}
      {state === 'ready' && rows.length === 0 && <div className="state">거래 내역이 없어요.</div>}
      {state === 'ready' && rows.length > 0 && (
        <ul className="ac-tx">
          {rows.map((t) => (
            <li key={t.id}>
              <div><strong>{t.counterpartyName ?? TX_LABEL[t.type] ?? t.type}</strong><small>{fmt(t.createdAt)}{t.memo && ` · ${t.memo}`}</small></div>
              <div className="ac-tx-amt">
                <b className={t.direction === 'in' ? 'in' : ''}>{t.direction === 'in' ? '+' : t.direction === 'out' ? '-' : ''}{won(t.amount)}</b>
                <small>잔액 {won(t.balanceAfter)}</small>
              </div>
            </li>
          ))}
        </ul>
      )}
      {state === 'ready' && more && <button type="button" className="auth-btn" onClick={() => void loadMore()}>더 보기</button>}
    </section>
  )
}

const TX_LABEL: Record<string, string> = { open: '계좌 개설', close: '계좌 해지', interest: '이자', deposit: '입금' }
