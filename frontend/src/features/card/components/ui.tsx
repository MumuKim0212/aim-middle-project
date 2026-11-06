import { useEffect, useRef, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { CardStatus, CardType } from '../api/types'

export const btnPrimary =
  'inline-flex h-11 items-center justify-center rounded-lg bg-brand px-4 text-sm font-semibold text-white disabled:opacity-40'
export const btnOutline =
  'inline-flex h-11 items-center justify-center rounded-lg border border-gray-300 bg-white px-4 text-sm text-gray-800 disabled:opacity-40'
export const inputClass =
  'h-11 w-full rounded-lg border border-gray-300 px-3 text-sm outline-none focus:border-brand disabled:bg-gray-100'

export function Loading() {
  return (
    <p role="status" className="py-12 text-center text-sm text-gray-500">
      불러오는 중...
    </p>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="mx-4 my-8 rounded-lg bg-gray-50 p-6 text-center">
      <p className="text-sm text-gray-700">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className={`${btnOutline} mt-4`}>
          다시 시도
        </button>
      )}
    </div>
  )
}

export function EmptyBox({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div className="mx-4 my-8 rounded-lg bg-gray-50 p-6 text-center">
      <p className="text-sm text-gray-600">{message}</p>
      {children && <div className="mt-4 flex justify-center gap-2">{children}</div>}
    </div>
  )
}

export function PageHeader({ title, backTo }: { title: string; backTo?: string }) {
  const navigate = useNavigate()
  return (
    <div className="flex items-center gap-2 border-b border-gray-200 px-4 pb-3 pt-1">
      {backTo ? (
        <Link to={backTo} aria-label="뒤로 가기" className="p-1 text-lg">
          ←
        </Link>
      ) : (
        <button type="button" aria-label="뒤로 가기" onClick={() => navigate(-1)} className="p-1 text-lg">
          ←
        </button>
      )}
      <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
    </div>
  )
}

const STATUS_BADGE: Record<CardStatus, { label: string; cls: string } | null> = {
  active: null,
  suspended: { label: '일시정지', cls: 'bg-status-suspended/10 text-status-suspended' },
  lost: { label: '분실', cls: 'bg-status-lost/10 text-status-lost' },
  terminated: { label: '해지', cls: 'bg-status-terminated/10 text-status-terminated' },
}

export function StatusBadge({ status }: { status: CardStatus }) {
  const badge = STATUS_BADGE[status]
  if (!badge) return null
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${badge.cls}`}>{badge.label}</span>
}

export function TypeBadge({ type }: { type: CardType }) {
  return (
    <span className="rounded bg-brand/10 px-1.5 py-0.5 text-xs font-medium text-brand">
      {type === 'credit' ? '신용' : '체크'}
    </span>
  )
}

export function UsageBar({ rate }: { rate: number }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={rate}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="한도 이용 비율"
      className="h-2.5 w-full overflow-hidden rounded-full bg-gray-200"
    >
      <div className="h-full bg-brand" style={{ width: `${rate}%` }} />
    </div>
  )
}

export function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <dt className="shrink-0 text-gray-500">{label}</dt>
      <dd className="text-right text-gray-900">{children}</dd>
    </div>
  )
}

export function Section({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="px-4 py-4">
      {title && <h2 className="mb-2 text-sm font-semibold text-gray-900">{title}</h2>}
      {children}
    </section>
  )
}

/** 네이티브 <dialog>를 쓴다. 포커스 가두기와 Esc 처리를 브라우저가 해준다. */
export function Modal({
  label, children, closable = true, onClose,
}: { label: string; children: ReactNode; closable?: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (d && !d.open) d.showModal()
    return () => d?.close()
  }, [])
  return (
    <dialog
      ref={ref}
      aria-label={label}
      onCancel={(e) => {
        e.preventDefault()
        if (closable) onClose()
      }}
      className="m-auto w-[calc(100%-32px)] max-w-[380px] rounded-xl p-0 backdrop:bg-black/40"
    >
      <div className="p-5">{children}</div>
    </dialog>
  )
}

export function ConfirmDialog({
  title, message, confirmLabel = '계속', onConfirm, onClose,
}: { title: string; message: string; confirmLabel?: string; onConfirm: () => void; onClose: () => void }) {
  return (
    <Modal label={title} onClose={onClose}>
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      <p className="mt-2 text-sm text-gray-600">{message}</p>
      <div className="mt-5 flex gap-2">
        <button type="button" onClick={onClose} className={`${btnOutline} flex-1`}>
          취소
        </button>
        <button type="button" onClick={onConfirm} className={`${btnPrimary} flex-1`}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
