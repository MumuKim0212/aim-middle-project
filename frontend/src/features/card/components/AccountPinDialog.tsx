import { useEffect, useState } from 'react'
import { ApiError } from '../api/errors'
import { btnOutline, btnPrimary, inputClass, Modal } from './ui'

// 같은 계좌의 잠금은 어느 팝업에서든 이어진다. performance.now() 기준이라 기기 시계를 바꿔도 영향이 없다.
// 새로고침하면 사라지고, 그 뒤 첫 제출에서 서버가 429로 알려준다 (서버가 기준).
const locks = new Map<string, number>()

type Props = {
  accountId: string
  account: { bankName: string; accountMasked: string }
  title: string
  description?: string
  confirmLabel: string
  onSubmit: (pin: string) => Promise<void>
  onSuccess: () => void
  /** 계좌 암호 오류가 아닌 오류. 팝업을 닫은 뒤 호출한 화면이 처리한다 */
  onError: (err: ApiError) => void
  onClose: () => void
}

export default function AccountPinDialog(p: Props) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [lockedUntil, setLockedUntil] = useState(() => locks.get(p.accountId) ?? 0)
  const [now, setNow] = useState(() => performance.now())
  const locked = lockedUntil > now
  const remaining = Math.max(0, Math.ceil((lockedUntil - now) / 1000))

  useEffect(() => {
    if (!locked) return
    const id = setInterval(() => setNow(performance.now()), 1000)
    return () => clearInterval(id)
  }, [locked])

  const submit = async () => {
    if (pin.length !== 4 || busy || locked) return
    const value = pin
    setBusy(true)
    setMessage(null)
    setPin('')
    try {
      await p.onSubmit(value)
      p.onSuccess()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'ACCOUNT_PIN_MISMATCH') {
        setMessage(`계좌 암호가 올바르지 않습니다. (남은 시도 ${String(e.details?.remainingAttempts)}회)`)
      } else if (e instanceof ApiError && e.code === 'ACCOUNT_PIN_LOCKED') {
        const until = performance.now() + Number(e.details?.retryAfterSeconds ?? 300) * 1000
        locks.set(p.accountId, until)
        setLockedUntil(until)
        setNow(performance.now())
      } else {
        p.onError(e instanceof ApiError ? e : new ApiError(0, 'NETWORK_ERROR', '네트워크 오류'))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal label={p.title} closable={!busy} onClose={p.onClose}>
      <h2 className="text-base font-semibold text-gray-900">{p.title}</h2>
      {p.description && <p className="mt-1 text-sm text-gray-600">{p.description}</p>}
      <p className="mt-3 rounded bg-gray-50 px-3 py-2 text-sm text-gray-700">
        {p.account.bankName} {p.account.accountMasked}
      </p>
      <label className="mt-3 block text-sm text-gray-700" htmlFor="account-pin">
        계좌 암호 (숫자 4자리)
      </label>
      <input
        id="account-pin"
        type="password"
        inputMode="numeric"
        maxLength={4}
        autoComplete="off"
        autoFocus
        value={pin}
        disabled={busy || locked}
        onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        className={`${inputClass} mt-1 tracking-[0.5em]`}
      />
      <p aria-live="polite" className="mt-2 min-h-5 text-sm text-warning">
        {locked
          ? `계좌 암호를 5회 연속 틀려 ${Math.floor(remaining / 60)}분 ${remaining % 60}초 뒤에 다시 입력할 수 있습니다.`
          : message}
      </p>
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={p.onClose} disabled={busy} className={`${btnOutline} flex-1`}>
          취소
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={pin.length !== 4 || busy || locked}
          className={`${btnPrimary} flex-1`}
        >
          {busy ? '처리 중...' : p.confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
