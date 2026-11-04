import { Link } from 'react-router-dom'
import { getUpcomingBilling } from '../api/cardApi'
import type { BillingPayment } from '../api/types'
import { EmptyBox, ErrorBox, Loading, PageHeader, StatusBadge, btnOutline } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { kstDate } from '../lib/dates'
import { formatDate, formatWon } from '../lib/format'

function PaymentGroup({ group }: { group: BillingPayment }) {
  const { paymentAccount: acc } = group
  return (
    <section className="mx-4 mt-4 rounded-lg border border-gray-200">
      <div className="border-b border-gray-100 p-4">
        <p className="text-xs text-gray-500">
          {formatDate(group.paymentDate)} 결제 · {acc.bankName} {acc.accountMasked}
        </p>
        <p className="mt-1 text-lg font-semibold text-gray-900">{formatWon(group.amount)}</p>
        {group.balanceStatus === 'insufficient' && (
          <p role="alert" className="mt-2 text-sm text-warning">
            ⚠ 결제 계좌 잔액이 부족합니다. 부족 금액 {formatWon(group.shortfall ?? 0)}
          </p>
        )}
        {group.balanceStatus === 'unavailable' && (
          <p className="mt-2 text-sm text-gray-500">잔액을 확인하지 못했습니다</p>
        )}
      </div>
      {group.cards.map((c) => (
        <details key={c.cardId} className="border-b border-gray-100 last:border-b-0">
          <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-sm">
            <span className="flex items-center gap-1.5">
              {c.cardName} {c.cardNumberLast4} <StatusBadge status={c.status} />
            </span>
            <span className="font-semibold">{formatWon(c.amount)}</span>
          </summary>
          <p className="px-4 text-xs text-gray-500">
            이용기간 {formatDate(c.usagePeriod.from)} ~ {formatDate(c.usagePeriod.to)}
          </p>
          <ul className="px-4 pb-3 pt-1">
            {c.items.map((it, i) => (
              <li key={i} className="flex justify-between py-1.5 text-sm text-gray-700">
                <span>
                  {formatDate(kstDate(Date.parse(it.occurredAt)))} {it.merchant}
                  {it.installment && ` (${it.installment.round}/${it.installment.months}회차)`}
                </span>
                <span>{it.kind === 'cancel' ? `-${formatWon(it.amount)}` : formatWon(it.amount)}</span>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </section>
  )
}

export default function BillingPage() {
  const { data, error, loading, reload } = useAsync(getUpcomingBilling, [])
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox message="청구 정보를 불러오지 못했습니다" onRetry={reload} />

  const current = data.payments.filter((p) => p.isCurrentMonth)
  const later = data.payments.filter((p) => !p.isCurrentMonth)

  return (
    <main>
      <PageHeader title="청구·결제 예정 금액" backTo="/card" />
      {!data.hasCreditCard ? (
        <EmptyBox message="신용카드가 없습니다. 체크카드는 이용 즉시 결제되어 청구 내역이 없습니다">
          <Link to="/card" className={btnOutline}>
            내 카드 보기
          </Link>
        </EmptyBox>
      ) : (
        <>
          <div className="px-4 py-4">
            <p className="text-sm text-gray-500">이번 달 결제 예정액</p>
            {data.thisMonthTotal > 0 ? (
              <p className="mt-1 text-2xl font-semibold text-gray-900">{formatWon(data.thisMonthTotal)}</p>
            ) : (
              <p className="mt-1 text-sm text-gray-600">이번 달 결제 예정 금액이 없습니다</p>
            )}
            {data.nextPaymentDate && (
              <p className="mt-1 text-sm text-gray-600">
                결제일 {formatDate(data.nextPaymentDate)} ·{' '}
                {data.daysUntilPayment === 0 ? '오늘 결제' : `D-${data.daysUntilPayment}`}
              </p>
            )}
          </div>
          {current.map((g) => (
            <PaymentGroup key={`${g.paymentDate}${g.paymentAccount.accountId}`} group={g} />
          ))}
          {later.length > 0 && (
            <>
              <h2 className="px-4 pt-6 text-sm font-semibold text-gray-900">다음 결제 예정</h2>
              {later.map((g) => (
                <PaymentGroup key={`${g.paymentDate}${g.paymentAccount.accountId}`} group={g} />
              ))}
            </>
          )}
        </>
      )}
    </main>
  )
}
