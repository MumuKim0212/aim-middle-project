import { Link, Navigate, useLocation } from 'react-router-dom'
import type { CardApplicationResult } from '../api/types'
import { InfoRow, PageHeader, Section, btnOutline, btnPrimary } from '../components/ui'
import { formatWon } from '../lib/format'

export default function ApplyResultPage() {
  const result = (useLocation().state as { result?: CardApplicationResult } | null)?.result
  // 새로고침하거나 주소로 직접 열면 결과 데이터가 없으므로 목록으로 보낸다
  if (!result) return <Navigate to="/card" replace />

  const card = result.card
  return (
    <main>
      <PageHeader title="카드 신청 결과" backTo="/card" />
      {result.status === 'approved' && card ? (
        <Section>
          <p role="status" className="text-base font-semibold text-gray-900">
            {card.type === 'credit' ? '신용카드' : '체크카드'} 발급이 완료되었습니다
          </p>
          <dl className="mt-2 divide-y divide-gray-100">
            <InfoRow label="카드">{card.name} {card.numberMasked.slice(-4)}</InfoRow>
            <InfoRow label="유효기간">{card.expiry}</InfoRow>
            <InfoRow label="결제 계좌">{card.paymentAccount.bankName} {card.paymentAccount.accountMasked}</InfoRow>
            {card.paymentDay !== null && <InfoRow label="결제일">매월 {card.paymentDay}일</InfoRow>}
            {result.grantedLimit !== null && <InfoRow label="신용 한도">{formatWon(result.grantedLimit)}</InfoRow>}
          </dl>
          {result.estimatedDeliveryBusinessDays && (
            <p className="mt-3 text-sm text-gray-600">
              카드는 입력하신 주소로 {result.estimatedDeliveryBusinessDays.min}~{result.estimatedDeliveryBusinessDays.max}영업일 내 배송됩니다
            </p>
          )}
          <Link to="/card" className={`${btnPrimary} mt-4 w-full`}>내 카드 보기</Link>
        </Section>
      ) : (
        <Section>
          <p role="status" className="text-base font-semibold text-gray-900">카드를 발급하지 못했습니다</p>
          <p className="mt-2 text-sm text-gray-600">소득 확인이 어려워 발급이 어렵습니다</p>
          <div className="mt-4 flex gap-2">
            <Link to="/card/apply" className={`${btnOutline} flex-1`}>다시 신청하기</Link>
            <Link to="/card" className={`${btnPrimary} flex-1`}>내 카드 보기</Link>
          </div>
        </Section>
      )}
    </main>
  )
}
