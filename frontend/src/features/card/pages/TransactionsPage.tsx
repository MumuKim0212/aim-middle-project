import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getTransaction, listCards, listTransactions } from '../api/cardApi'
import type { TransactionDetail, TransactionItem, TransactionSummary } from '../api/types'
import { EmptyBox, ErrorBox, Loading, PageHeader, btnOutline, inputClass } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { addMonths, isValidDate, kstDate, kstTime, monthStart } from '../lib/dates'
import { formatDate, formatWon } from '../lib/format'

const PRESETS = [['this_month', '이번 달'], ['1m', '1개월'], ['3m', '3개월'], ['custom', '직접 입력']] as const
const KINDS = [['all', '전체'], ['approval', '승인'], ['cancel', '취소']] as const

/** 조회 기간 검사. 아직 다 채우지 않았으면 'incomplete' (조회도 문구도 없음) */
const rangeProblem = (from: string, to: string, t: string): string | null => {
  if (!from || !to) return 'incomplete'
  if (!isValidDate(from) || !isValidDate(to)) return '날짜 형식을 확인해 주세요'
  if (from > to) return '시작일이 종료일보다 늦을 수 없습니다'
  if (to > t) return '종료일은 오늘을 넘길 수 없습니다'
  if (from < addMonths(to, -12)) return '최대 12개월까지 조회할 수 있습니다'
  return null
}

type Result = { summary: TransactionSummary; items: TransactionItem[]; next: string | null }

export default function TransactionsPage() {
  const [sp, setSp] = useSearchParams()
  const T = kstDate(Date.now())
  const cardId = sp.get('cardId') ?? ''
  const preset = sp.get('preset') ?? 'this_month'
  const kind = (sp.get('kind') ?? 'all') as 'all' | 'approval' | 'cancel'
  const merchant = sp.get('merchant') ?? ''
  const range =
    preset === 'custom' ? { from: sp.get('from') ?? '', to: sp.get('to') ?? '' }
      : preset === '1m' ? { from: addMonths(T, -1), to: T }
      : preset === '3m' ? { from: addMonths(T, -3), to: T }
      : { from: monthStart(T), to: T }
  const problem = rangeProblem(range.from, range.to, T)

  const set = (patch: Record<string, string>) =>
    setSp((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v)
        else next.delete(k)
      }
      return next
    }, { replace: true })

  const cards = useAsync(() => listCards({ includeTerminated: true }), [])
  const [q, setQ] = useState(merchant)
  const [result, setResult] = useState<Result | null>(null)
  const [status, setStatus] = useState<'idle' | 'loading' | 'failed'>('idle')
  const [moreFailed, setMoreFailed] = useState(false)
  const [opened, setOpened] = useState<Record<string, TransactionDetail | 'loading' | 'failed'>>({})
  const reqId = useRef(0)

  const base = { cardId: cardId || undefined, from: range.from, to: range.to, kind, merchant, limit: 20 }
  const load = () => {
    if (problem) return
    const id = ++reqId.current
    setStatus('loading')
    setMoreFailed(false)
    listTransactions(base)
      .then((r) => id === reqId.current && (setResult({ summary: r.summary, items: r.items, next: r.nextCursor }), setStatus('idle')))
      .catch(() => id === reqId.current && setStatus('failed'))
  }
  // 마지막 요청의 응답만 화면에 반영한다 (reqId)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [cardId, range.from, range.to, kind, merchant, problem])

  const more = () => {
    if (!result?.next) return
    const id = reqId.current
    listTransactions({ ...base, cursor: result.next })
      .then((r) => id === reqId.current && setResult({
        summary: r.summary,
        items: [...result.items, ...r.items.filter((x) => !result.items.some((y) => y.id === x.id))],
        next: r.nextCursor,
      }))
      .catch(() => setMoreFailed(true))
  }

  const openCancel = (t: TransactionItem) => {
    if (t.kind !== 'cancel' || opened[t.id]) return
    setOpened((o) => ({ ...o, [t.id]: 'loading' }))
    getTransaction(t.id)
      .then((d) => setOpened((o) => ({ ...o, [t.id]: d })))
      .catch(() => setOpened((o) => ({ ...o, [t.id]: 'failed' })))
  }

  const groups = new Map<string, TransactionItem[]>()
  for (const t of result?.items ?? []) {
    const d = kstDate(Date.parse(t.occurredAt))
    groups.set(d, [...(groups.get(d) ?? []), t])
  }

  return (
    <main>
      <PageHeader title="이용내역 조회" backTo="/cards" />
      <div className="space-y-3 px-4 py-3">
        <select
          aria-label="카드"
          value={cardId}
          onChange={(e) => set({ cardId: e.target.value })}
          className={inputClass}
        >
          <option value="">전체 카드</option>
          {cards.data?.items.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} {c.numberMasked.slice(-4)}
              {c.status === 'terminated' ? ' (해지)' : ''}
            </option>
          ))}
        </select>
        <div role="group" aria-label="기간" className="flex gap-1">
          {PRESETS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={preset === value}
              onClick={() => set({ preset: value === 'this_month' ? '' : value })}
              className={`h-9 flex-1 rounded-full border text-xs ${preset === value ? 'border-pill-active-border bg-pill-active font-semibold text-brand-dark' : 'border-gray-300'}`}
            >
              {label}
            </button>
          ))}
        </div>
        {preset === 'custom' && (
          <div className="flex items-center gap-2">
            <input type="date" aria-label="시작일" max={T} value={range.from} onChange={(e) => set({ from: e.target.value })} className={inputClass} />
            <span>~</span>
            <input type="date" aria-label="종료일" max={T} value={range.to} onChange={(e) => set({ to: e.target.value })} className={inputClass} />
          </div>
        )}
        {problem && problem !== 'incomplete' && <p role="alert" className="text-sm text-warning">{problem}</p>}
        <div role="group" aria-label="구분" className="flex gap-1">
          {KINDS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              onClick={() => set({ kind: value === 'all' ? '' : value })}
              className={`h-9 flex-1 rounded-full border text-xs ${kind === value ? 'border-pill-active-border bg-pill-active font-semibold text-brand-dark' : 'border-gray-300'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            set({ merchant: q.trim() })
          }}
          className="flex gap-2"
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="가맹점 검색"
            aria-label="가맹점 검색"
            className={inputClass}
          />
          <button type="submit" className={btnOutline}>
            검색
          </button>
        </form>
      </div>

      {problem === 'incomplete' ? null : problem ? null : status === 'failed' ? (
        <ErrorBox message="이용내역을 불러오지 못했습니다" onRetry={load} />
      ) : !result || (status === 'loading' && result.items.length === 0) ? (
        <Loading />
      ) : (
        <>
          <dl className="mx-4 grid grid-cols-3 gap-2 rounded-lg bg-gray-50 p-3 text-center text-xs text-gray-600">
            <div><dt>승인 합계</dt><dd className="mt-1 text-sm font-semibold text-gray-900">{formatWon(result.summary.approvalTotal)}</dd></div>
            <div><dt>취소 합계</dt><dd className="mt-1 text-sm font-semibold text-gray-900">{formatWon(result.summary.cancelTotal)}</dd></div>
            <div><dt>순 이용액</dt><dd className="mt-1 text-sm font-semibold text-gray-900">{formatWon(result.summary.netTotal)}</dd></div>
          </dl>
          {result.items.length === 0 ? (
            <EmptyBox message="조건에 맞는 이용내역이 없습니다">
              <button type="button" className={btnOutline} onClick={() => { setQ(''); setSp({}, { replace: true }) }}>
                조건 초기화
              </button>
            </EmptyBox>
          ) : (
            [...groups].map(([date, items]) => (
              <section key={date} className="mt-4">
                <h2 className="bg-gray-50 px-4 py-1.5 text-xs font-semibold text-gray-600">{formatDate(date)}</h2>
                <ul>
                  {items.map((t) => {
                    const detail = opened[t.id]
                    return (
                      <li key={t.id} className="border-b border-gray-100 px-4 py-3">
                        <button type="button" onClick={() => openCancel(t)} className="flex w-full items-center justify-between text-left">
                          <div>
                            <p className="text-sm text-gray-900">{t.merchant}</p>
                            <p className="mt-0.5 text-xs text-gray-500">
                              {kstTime(Date.parse(t.occurredAt))}
                              {!cardId && ` · ${t.cardName} ${t.cardNumberLast4}`}
                              {t.cardType === 'credit' && t.kind === 'approval' &&
                                ` · ${t.installmentMonths === 0 ? '일시불' : `${t.installmentMonths}개월`}`}
                            </p>
                          </div>
                          <div className="text-right">
                            <p className={`text-sm font-semibold ${t.kind === 'cancel' ? 'text-status-lost' : 'text-gray-900'}`}>
                              {t.kind === 'cancel' ? `-${formatWon(t.amount)}` : formatWon(t.amount)}
                            </p>
                            <p className="mt-0.5 text-xs text-gray-500">{t.kind === 'cancel' ? '취소' : '승인'}</p>
                          </div>
                        </button>
                        {detail === 'loading' && <p className="mt-2 text-xs text-gray-500">원 거래를 불러오는 중...</p>}
                        {detail === 'failed' && <p className="mt-2 text-xs text-warning">원 거래를 불러오지 못했습니다</p>}
                        {detail && typeof detail === 'object' && (
                          <p className="mt-2 rounded bg-gray-50 p-2 text-xs text-gray-600">
                            {detail.original
                              ? `원 승인: ${formatDate(kstDate(Date.parse(detail.original.occurredAt)))} · ${detail.original.merchant} · ${formatWon(detail.original.amount)}`
                              : '원 거래 정보를 찾을 수 없습니다'}
                          </p>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </section>
            ))
          )}
          {moreFailed && (
            <p role="alert" className="px-4 py-3 text-center text-sm text-warning">
              더 불러오지 못했습니다 ·{' '}
              <button type="button" onClick={more} className="underline">
                다시 시도
              </button>
            </p>
          )}
          {result.next && !moreFailed && (
            <div className="px-4 py-4">
              <button type="button" onClick={more} className={`${btnOutline} w-full`}>
                더 보기
              </button>
            </div>
          )}
        </>
      )}
    </main>
  )
}
