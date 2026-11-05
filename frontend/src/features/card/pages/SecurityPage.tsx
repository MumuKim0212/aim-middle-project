import { useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { getCard, reportLost, resumeCard, suspendCard } from '../api/cardApi'
import type { ApiError } from '../api/errors'
import AccountPinDialog from '../components/AccountPinDialog'
import {
  ConfirmDialog, ErrorBox, Loading, Modal, PageHeader, Section, StatusBadge, TypeBadge, btnOutline, btnPrimary,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { formatDateTime } from '../lib/format'

type Flow = { kind: 'suspend' | 'resume' | 'lost'; stage: 'reason' | 'confirm' | 'pin' }

const DONE = { suspend: '일시정지 되었습니다', resume: '정지가 해제되었습니다', lost: '분실 신고가 접수되었습니다' }

export default function SecurityPage() {
  const { cardId = '' } = useParams()
  const { data: card, error, loading, reload } = useAsync(() => getCard(cardId), [cardId])
  const [flow, setFlow] = useState<Flow | null>(null)
  const [reason, setReason] = useState<'lost' | 'stolen'>('lost')
  const [notice, setNotice] = useState<string | null>(null)

  if (loading && !card) return <Loading />
  if (error?.code === 'CARD_NOT_FOUND') return <ErrorBox message="카드를 찾을 수 없습니다" />
  if (error || !card) return <ErrorBox message="카드 정보를 불러오지 못했습니다" onRetry={reload} />
  if (card.status === 'terminated') return <Navigate to={`/cards/${card.id}`} replace />

  const can = (a: (typeof card.availableActions)[number]) => card.availableActions.includes(a)

  const handleError = (err: ApiError) => {
    setFlow(null)
    if (err.code === 'CARD_STATE_INVALID') {
      setNotice('카드 상태가 이미 바뀌었습니다')
      reload()
    } else if (err.code === 'ACCOUNT_SERVICE_UNAVAILABLE') {
      setNotice('계좌 정보를 확인할 수 없어 처리하지 못했습니다. 잠시 후 다시 시도해 주세요')
    } else if (err.status === 0) {
      setNotice('처리 결과를 확인하는 중입니다')
      reload()
    } else {
      setNotice('처리하지 못했습니다. 잠시 후 다시 시도해 주세요')
    }
  }

  const submit = async (pin: string) => {
    if (flow?.kind === 'suspend') await suspendCard(card.id, pin)
    else if (flow?.kind === 'resume') await resumeCard(card.id, pin)
    else await reportLost(card.id, { reason, accountPin: pin })
  }

  return (
    <main>
      <PageHeader title="카드 분실·정지·재개" backTo={`/cards/${card.id}`} />
      <Section>
        <p className="flex items-center gap-1.5 text-base font-semibold text-gray-900">
          {card.name} {card.numberMasked.slice(-4)} <TypeBadge type={card.type} /> <StatusBadge status={card.status} />
        </p>
        <p className="mt-3 text-sm text-gray-700">
          {card.status === 'active' && '정상 이용 가능'}
          {card.status === 'suspended' && `일시정지 중${card.suspendedAt ? ` (${formatDateTime(card.suspendedAt)})` : ''}`}
          {card.status === 'lost' && '분실 신고됨'}
        </p>
        {card.status === 'lost' && card.lostAt && (
          <div className="mt-2 rounded-lg bg-status-lost/10 p-4 text-sm text-status-lost">
            <p>
              {formatDateTime(card.lostAt)} · 사유 {card.lostReason === 'stolen' ? '도난' : '분실'}
            </p>
            <p className="mt-1">고객센터로 재발급을 신청해 주세요.</p>
          </div>
        )}
      </Section>

      {notice && (
        <p role="status" className="mx-4 rounded-lg bg-gray-100 p-3 text-sm text-gray-800">
          {notice}
        </p>
      )}

      <div className="flex flex-col gap-2 px-4 py-4">
        {can('suspend') && (
          <button type="button" className={btnOutline} onClick={() => { setNotice(null); setFlow({ kind: 'suspend', stage: 'confirm' }) }}>
            일시정지
          </button>
        )}
        {can('resume') && (
          <button type="button" className={btnPrimary} onClick={() => { setNotice(null); setFlow({ kind: 'resume', stage: 'confirm' }) }}>
            정지 해제
          </button>
        )}
        {can('report_lost') && (
          <button type="button" className={btnOutline} onClick={() => { setNotice(null); setFlow({ kind: 'lost', stage: 'reason' }) }}>
            분실 신고
          </button>
        )}
      </div>

      {flow && flow.stage === 'reason' && (
        <Modal label="분실 신고 사유" onClose={() => setFlow(null)}>
          <h2 className="text-base font-semibold">분실 신고 사유</h2>
          <fieldset className="mt-3 space-y-2">
            {([['lost', '분실'], ['stolen', '도난']] as const).map(([v, label]) => (
              <label key={v} className="flex items-center gap-2 text-sm">
                <input type="radio" name="reason" checked={reason === v} onChange={() => setReason(v)} /> {label}
              </label>
            ))}
          </fieldset>
          <div className="mt-5 flex gap-2">
            <button type="button" onClick={() => setFlow(null)} className={`${btnOutline} flex-1`}>취소</button>
            <button type="button" onClick={() => setFlow({ kind: 'lost', stage: 'confirm' })} className={`${btnPrimary} flex-1`}>다음</button>
          </div>
        </Modal>
      )}
      {flow && flow.stage === 'confirm' && (
        <ConfirmDialog
          title={flow.kind === 'suspend' ? '일시정지' : flow.kind === 'resume' ? '정지 해제' : '분실 신고'}
          message={
            flow.kind === 'suspend' ? '이 카드의 모든 이용이 중단됩니다. 계속할까요?'
              : flow.kind === 'resume' ? '정지를 해제하고 다시 이용할 수 있게 합니다. 계속할까요?'
              : '신고하면 되돌릴 수 없고 이 카드는 다시 쓸 수 없습니다.'
          }
          onClose={() => setFlow(null)}
          onConfirm={() => setFlow({ ...flow, stage: 'pin' })}
        />
      )}
      {flow && flow.stage === 'pin' && (
        <AccountPinDialog
          accountId={card.paymentAccount.accountId}
          account={card.paymentAccount}
          title="계좌 암호 입력"
          description="결제 계좌의 암호를 입력해 주세요."
          confirmLabel="확인"
          onSubmit={submit}
          onSuccess={() => { setNotice(DONE[flow.kind]); setFlow(null); reload() }}
          onError={handleError}
          onClose={() => setFlow(null)}
        />
      )}
    </main>
  )
}
