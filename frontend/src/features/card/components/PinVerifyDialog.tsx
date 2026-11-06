import { useState } from 'react'
import PinKeypad from '../../../auth/PinKeypad'
import { ApiFail, callJson } from '../../../lib/http'
import { btnOutline, Modal } from './ui'

type Props = {
  description: string
  onVerified: (validForSeconds: number) => void
  onCancel: () => void
}

/** 간편비밀번호(6자리) 확인 팝업(S-08, docs/dev/card/frontend-spec.md 7.2). 틀린 횟수와 잠금은 서버가 센다. */
export default function PinVerifyDialog({ description, onVerified, onCancel }: Props) {
  const [busy, setBusy] = useState(false)
  const [locked, setLocked] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [reset, setReset] = useState(0)

  const submit = async (pin: string) => {
    setBusy(true)
    setMessage(null)
    try {
      const res = await callJson<{ validForSeconds: number }>('POST', '/api/auth/pin/verify', { pin })
      onVerified(res.validForSeconds)
    } catch (e) {
      const body = e instanceof ApiFail ? e.body : {}
      if (body.code === 'PIN_LOCKED') setLocked(true)
      setMessage(body.message ?? '확인하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      setReset((n) => n + 1)
      setBusy(false)
    }
  }

  return (
    <Modal label="간편비밀번호 확인" closable={!busy} onClose={onCancel}>
      <h2 className="text-base font-semibold text-gray-900">간편비밀번호를 입력해 주세요</h2>
      <p className="mt-1 text-sm text-gray-600">{description}</p>
      <div className="mt-3">
        <PinKeypad onComplete={(pin) => void submit(pin)} disabled={busy || locked} resetKey={reset} />
      </div>
      <p aria-live="polite" className="mt-2 min-h-5 text-sm text-warning">{message}</p>
      <button type="button" onClick={onCancel} disabled={busy} className={`${btnOutline} mt-3 w-full`}>
        취소
      </button>
    </Modal>
  )
}
