import { useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { checkTermination, getCard, terminateCard } from '../api/cardApi'
import type { ApiError } from '../api/errors'
import type { TerminateReason } from '../api/types'
import AccountPinDialog from '../components/AccountPinDialog'
import { ErrorBox, InfoRow, Loading, PageHeader, Section, btnOutline, btnPrimary } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { formatDate, formatDateTime, formatWon } from '../lib/format'

const REASONS: [TerminateReason, string][] = [
  ['unused', '사용하지 않음'], ['benefit_complaint', '연회비·혜택 불만'], ['other_card', '다른 카드를 사용'],
  ['lost_cleanup', '분실·도난 후 정리'], ['other', '기타'],
]

export default function TerminatePage() {
  const { cardId = '' } = useParams()
  const card = useAsync(() => getCard(cardId), [cardId])
  const check = useAsync(() => checkTermination(cardId), [cardId])
  const [reason, setReason] = useState<TerminateReason | null>(null)
  const [reasonTouched, setReasonTouched] = useState(false)
  const [ack, setAck] = useState(false)
  const [pinOpen, setPinOpen] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  if (done && card.data) {
    return (
      <main>
        <PageHeader title="카드 해지" backTo="/cards" />
        <Section>
          <p role="status" className="text-base font-semibold text-gray-900">카드가 해지되었습니다</p>
          <dl className="mt-2 divide-y divide-gray-100">
            <InfoRow label="카드">{card.data.name} {card.data.numberMasked.slice(-4)}</InfoRow>
            <InfoRow label="해지 일시">{formatDateTime(done)}</InfoRow>
          </dl>
          <Link to="/cards" className={`${btnPrimary} mt-4 w-full`}>내 카드 목록</Link>
        </Section>
      </main>
    )
  }

  if (card.loading || check.loading) return <Loading />
  if (card.error?.code === 'CARD_NOT_FOUND' || check.error?.code === 'CARD_NOT_FOUND') {
    return <ErrorBox message="카드를 찾을 수 없습니다" />
  }
  if (check.error?.code === 'CARD_STATE_INVALID') {
    return <ErrorBox message="해지할 수 없는 카드입니다" />
  }
  if (card.error || check.error || !card.data || !check.data) {
    return <ErrorBox message="카드 정보를 불러오지 못했습니다" onRetry={() => { card.reload(); check.reload() }} />
  }
  if (card.data.status === 'terminated') return <Navigate to={`/cards/${cardId}`} replace />

  const c = card.data
  const t = check.data
  // 분실 카드는 해지 사유를 미리 골라 둔다 (바꿀 수 있음)
  const selected = reasonTouched ? reason : c.status === 'lost' ? 'lost_cleanup' : null

  const handleError = (err: ApiError) => {
    setPinOpen(false)
    if (err.code === 'CARD_TERMINATE_BLOCKED_UNPAID') check.reload()
    else if (err.code === 'CARD_STATE_INVALID') setNotice('해지할 수 없는 카드입니다')
    else if (err.code === 'ACCOUNT_SERVICE_UNAVAILABLE') setNotice('계좌 정보를 확인할 수 없어 해지하지 못했습니다. 잠시 후 다시 시도해 주세요')
    else if (err.status === 0) { setNotice('해지 결과를 확인하는 중입니다'); card.reload(); check.reload() }
    else setNotice('해지하지 못했습니다. 잠시 후 다시 시도해 주세요')
  }

  return (
    <main>
      <PageHeader title="카드 해지" backTo={`/cards/${c.id}`} />
      <Section>
        <p className="text-base font-semibold text-gray-900">{c.name} {c.numberMasked.slice(-4)}</p>
        <p className="mt-1 text-sm text-gray-500">{c.paymentAccount.bankName} {c.paymentAccount.accountMasked}</p>
      </Section>

      {!t.canTerminate ? (
        <Section>
          <div role="alert" className="rounded-lg bg-gray-50 p-4 text-sm text-gray-700">
            <p className="font-semibold">미결제 금액이 있어 해지할 수 없습니다</p>
            <p className="mt-2">미결제 금액 {formatWon(t.unpaidAmount)}</p>
            {t.firstDueDate && <p>처음 결제되는 날 {formatDate(t.firstDueDate)}</p>}
            <p className="mt-2">미결제 금액을 모두 결제한 뒤 해지할 수 있습니다.</p>
          </div>
          <div className="mt-4 flex gap-2">
            <Link to="/cards/billing" className={`${btnOutline} flex-1`}>청구·결제 예정 금액 보기</Link>
            <Link to={`/cards/${c.id}`} className={`${btnOutline} flex-1`}>카드 상세로</Link>
          </div>
        </Section>
      ) : (
        <>
          <Section title="해지 사유 (선택)">
            <fieldset className="space-y-2">
              {REASONS.map(([v, label]) => (
                <label key={v} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="terminate-reason" checked={selected === v} onChange={() => { setReasonTouched(true); setReason(v) }} /> {label}
                </label>
              ))}
            </fieldset>
          </Section>
          <Section>
            <ul className="list-disc space-y-1 pl-5 text-sm text-gray-600">
              <li>해지 즉시 카드 이용이 모두 중단된다.</li>
              <li>이용내역은 해지 후에도 조회할 수 있다.</li>
              <li>카드는 직접 가위로 잘라 폐기해 주세요.</li>
            </ul>
            <label className="mt-3 flex items-start gap-2 text-sm text-gray-800">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
              해지하면 되돌릴 수 없고, 이 카드는 다시 쓸 수 없습니다
            </label>
            {notice && <p role="status" className="mt-3 text-sm text-warning">{notice}</p>}
            <button type="button" disabled={!ack} onClick={() => { setNotice(null); setPinOpen(true) }} className={`${btnPrimary} mt-4 w-full`}>
              해지하기
            </button>
          </Section>
        </>
      )}

      {pinOpen && (
        <AccountPinDialog
          accountId={c.paymentAccount.accountId}
          account={c.paymentAccount}
          title="계좌 암호 입력"
          description="카드를 해지하려면 결제 계좌의 암호를 입력해 주세요."
          confirmLabel="해지하기"
          onSubmit={async (pin) => {
            const res = await terminateCard(c.id, { reason: selected, acknowledged: true, accountPin: pin })
            setDone(res.terminatedAt)
          }}
          onSuccess={() => setPinOpen(false)}
          onError={handleError}
          onClose={() => setPinOpen(false)}
        />
      )}
    </main>
  )
}
