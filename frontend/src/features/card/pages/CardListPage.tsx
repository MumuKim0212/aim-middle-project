import { useState } from 'react'
import { Link } from 'react-router-dom'
import { listCards } from '../api/cardApi'
import type { CardSummary } from '../api/types'
import { EmptyBox, ErrorBox, Loading, PageHeader, StatusBadge, TypeBadge, btnPrimary } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

export function CardRow({ card, to }: { card: CardSummary; to: string }) {
  return (
    <li>
      <Link to={to} className="flex items-center justify-between border-b border-gray-100 px-4 py-4">
        <div>
          <p className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
            {card.name} <TypeBadge type={card.type} /> <StatusBadge status={card.status} />
          </p>
          <p className="mt-1 text-sm text-gray-500">{card.numberMasked}</p>
        </div>
        <span aria-hidden className="text-gray-400">
          ›
        </span>
      </Link>
    </li>
  )
}

export default function CardListPage() {
  // shortcut: 해지 카드를 한 번에 받아 나눈다. 명세는 토글을 열 때 includeTerminated=true로 다시 조회한다.
  const { data, error, loading, reload } = useAsync(() => listCards({ includeTerminated: true }), [])
  const [showTerminated, setShowTerminated] = useState(false)

  if (loading) return <Loading />
  if (error || !data) return <ErrorBox message="카드 정보를 불러오지 못했습니다" onRetry={reload} />

  const live = data.items.filter((c) => c.status !== 'terminated')
  const gone = data.items.filter((c) => c.status === 'terminated')

  return (
    <main>
      <PageHeader title="내 카드" backTo="/" />
      <div className="flex items-center justify-between px-4 py-3">
        <p className="text-sm text-gray-600">{live.length}장</p>
        <Link to="/card/apply" className={`${btnPrimary} h-9`}>
          카드 신청
        </Link>
      </div>
      {live.length === 0 ? (
        <EmptyBox message="보유한 카드가 없습니다">
          <Link to="/card/apply" className={btnPrimary}>
            카드 신청
          </Link>
        </EmptyBox>
      ) : (
        <ul>
          {live.map((c) => (
            <CardRow key={c.id} card={c} to={`/card/${c.id}`} />
          ))}
        </ul>
      )}
      {gone.length > 0 && (
        <div className="px-4 py-3">
          <button
            type="button"
            aria-expanded={showTerminated}
            onClick={() => setShowTerminated((v) => !v)}
            className="text-sm text-gray-600 underline"
          >
            해지된 카드 보기 ({gone.length})
          </button>
          {showTerminated && (
            <ul className="mt-2">
              {gone.map((c) => (
                <CardRow key={c.id} card={c} to={`/card/${c.id}`} />
              ))}
            </ul>
          )}
        </div>
      )}
    </main>
  )
}
