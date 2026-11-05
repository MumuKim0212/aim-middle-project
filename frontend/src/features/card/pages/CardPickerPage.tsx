import { Link } from 'react-router-dom'
import { listCards } from '../api/cardApi'
import { EmptyBox, ErrorBox, Loading, PageHeader, btnPrimary } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { CardRow } from './CardListPage'

const TEXT = {
  security: { title: '카드 분실·정지·재개', empty: '처리할 수 있는 카드가 없습니다' },
  limit: { title: '한도 조회', empty: '조회할 수 있는 카드가 없습니다' },
} as const

/** 메뉴에서 들어왔을 때 카드를 먼저 고르는 화면 (해지된 카드는 목록에 없다) */
export default function CardPickerPage({ purpose }: { purpose: keyof typeof TEXT }) {
  const { data, error, loading, reload } = useAsync(() => listCards(), [])
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox message="카드 정보를 불러오지 못했습니다" onRetry={reload} />

  return (
    <main>
      <PageHeader title={TEXT[purpose].title} backTo="/" />
      <p className="px-4 py-3 text-sm text-gray-600">카드를 선택해 주세요.</p>
      {data.items.length === 0 ? (
        <EmptyBox message={TEXT[purpose].empty}>
          <Link to="/cards/apply" className={btnPrimary}>
            카드 신청
          </Link>
        </EmptyBox>
      ) : (
        <ul>
          {data.items.map((c) => (
            <CardRow key={c.id} card={c} to={`/cards/${c.id}/${purpose}`} />
          ))}
        </ul>
      )}
    </main>
  )
}
