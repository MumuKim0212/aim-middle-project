import { Link, useParams } from 'react-router-dom'
import { getCard } from '../api/cardApi'
import { ErrorBox, InfoRow, Loading, PageHeader, Section, StatusBadge, TypeBadge, UsageBar, btnOutline } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { formatDate, formatDateTime, formatRate, formatWon } from '../lib/format'

export default function CardDetailPage() {
  const { cardId = '' } = useParams()
  const { data: card, error, loading, reload } = useAsync(() => getCard(cardId), [cardId])

  if (loading) return <Loading />
  if (error?.code === 'CARD_NOT_FOUND') {
    return <ErrorBox message="카드를 찾을 수 없습니다" />
  }
  if (error || !card) return <ErrorBox message="카드 정보를 불러오지 못했습니다" onRetry={reload} />

  const can = (a: (typeof card.availableActions)[number]) => card.availableActions.includes(a)

  return (
    <main>
      <PageHeader title="카드 상세" backTo="/cards" />
      <Section>
        <p className="flex items-center gap-1.5 text-base font-semibold text-gray-900">
          {card.name} <TypeBadge type={card.type} /> <StatusBadge status={card.status} />
        </p>
        <dl className="mt-2 divide-y divide-gray-100">
          <InfoRow label="카드 번호">{card.numberMasked}</InfoRow>
          <InfoRow label="유효기간">{card.expiry}</InfoRow>
          <InfoRow label="발급일">{formatDate(card.issuedAt)}</InfoRow>
        </dl>
      </Section>

      {card.status === 'lost' && card.lostAt && (
        <div role="note" className="mx-4 rounded-lg bg-status-lost/10 p-4 text-sm text-status-lost">
          <p className="font-semibold">분실 신고된 카드입니다</p>
          <p className="mt-1">
            {formatDateTime(card.lostAt)} · 사유 {card.lostReason === 'stolen' ? '도난' : '분실'}
          </p>
          <p className="mt-1">고객센터로 재발급을 신청해 주세요.</p>
        </div>
      )}

      <Section title="결제 계좌">
        <dl className="divide-y divide-gray-100">
          <InfoRow label="계좌">
            {card.paymentAccount.bankName} {card.paymentAccount.accountMasked}
          </InfoRow>
          {card.paymentDay !== null && <InfoRow label="결제일">매월 {card.paymentDay}일</InfoRow>}
        </dl>
      </Section>

      <Section title="한도">
        {card.limit ? (
          <div>
            <UsageBar rate={card.limit.usageRate} />
            <dl className="mt-2 divide-y divide-gray-100">
              <InfoRow label="이용 비율">{formatRate(card.limit.usageRate)}</InfoRow>
              <InfoRow label="총 한도">{formatWon(card.limit.total)}</InfoRow>
              <InfoRow label="이용 금액">{formatWon(card.limit.used)}</InfoRow>
              <InfoRow label="잔여 한도">{formatWon(card.limit.remaining)}</InfoRow>
            </dl>
          </div>
        ) : (
          card.debitLimit && (
            <dl className="divide-y divide-gray-100">
              <InfoRow label="1회 한도">{formatWon(card.debitLimit.perTx)}</InfoRow>
              <InfoRow label="1일 한도">{formatWon(card.debitLimit.perDay)}</InfoRow>
            </dl>
          )
        )}
      </Section>

      <div className="flex flex-col gap-2 px-4 py-4">
        {can('view_transactions') && (
          <Link to={`/cards/transactions?cardId=${card.id}`} className={btnOutline}>
            이용내역 보기
          </Link>
        )}
        {can('view_limit') && (
          <Link to={`/cards/${card.id}/limit`} className={btnOutline}>
            한도 조회
          </Link>
        )}
        {(can('suspend') || can('resume') || can('report_lost')) && (
          <Link to={`/cards/${card.id}/security`} className={btnOutline}>
            {can('resume') ? '정지 해제·분실 신고' : '일시정지·분실 신고'}
          </Link>
        )}
        {can('terminate') && (
          <Link to={`/cards/${card.id}/terminate`} className="py-2 text-center text-sm text-gray-500 underline">
            카드 해지
          </Link>
        )}
      </div>
    </main>
  )
}
