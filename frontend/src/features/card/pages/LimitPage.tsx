import { useParams } from 'react-router-dom'
import { getCardLimit } from '../api/cardApi'
import { ErrorBox, InfoRow, Loading, PageHeader, Section, StatusBadge, TypeBadge, UsageBar } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { formatRate, formatWon } from '../lib/format'

export default function LimitPage() {
  const { cardId = '' } = useParams()
  const { data, error, loading, reload } = useAsync(() => getCardLimit(cardId), [cardId])

  if (loading) return <Loading />
  if (error?.code === 'CARD_NOT_FOUND') return <ErrorBox message="카드를 찾을 수 없습니다" />
  if (error?.code === 'CARD_STATE_INVALID') return <ErrorBox message="해지된 카드입니다" />
  if (error || !data) return <ErrorBox message="한도 정보를 불러오지 못했습니다" onRetry={reload} />

  const { credit, debit } = data
  return (
    <main>
      <PageHeader title="한도 조회" backTo={`/card/${cardId}`} />
      <Section>
        <p className="flex items-center gap-1.5 text-sm text-gray-700">
          <TypeBadge type={data.type} /> <StatusBadge status={data.status} />
        </p>
      </Section>
      {credit && (
        <Section>
          {credit.used === 0 && <p className="mb-2 text-sm text-gray-500">사용한 한도가 없습니다</p>}
          {credit.remaining === 0 && <p className="mb-2 text-sm text-warning">한도를 모두 사용했습니다</p>}
          <UsageBar rate={credit.usageRate} />
          <dl className="mt-3 divide-y divide-gray-100">
            <InfoRow label="이용 비율">{formatRate(credit.usageRate)}</InfoRow>
            <InfoRow label="총 한도">{formatWon(credit.total)}</InfoRow>
            <InfoRow label="이용 금액">{formatWon(credit.used)}</InfoRow>
            <InfoRow label="잔여 한도">{formatWon(credit.remaining)}</InfoRow>
          </dl>
        </Section>
      )}
      {debit && (
        <Section>
          <dl className="divide-y divide-gray-100">
            <InfoRow label="1회 한도">{formatWon(debit.perTx)}</InfoRow>
            <InfoRow label="1일 한도">{formatWon(debit.perDay)}</InfoRow>
          </dl>
        </Section>
      )}
    </main>
  )
}
