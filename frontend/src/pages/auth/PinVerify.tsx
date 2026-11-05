import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import PinKeypad from '../../auth/PinKeypad'
import { ApiFail, callJson, safeNext } from '../../lib/http'

/**
 * 2차 인증(S-08). 이체 같은 중요 동작 직전에 계좌 파트가 이 화면으로 보낸다.
 *   /auth/pin/verify?next=/accounts/transfer&desc=OOO 계좌로 10,000원 이체
 * 통과하면 5분 동안 서버가 기억하고(pin_verified), next 로 돌아간다. 취소하면 이전 화면으로 간다.
 */
export default function PinVerify() {
  const nav = useNavigate()
  const { refresh } = useAuth()
  const [params] = useSearchParams()
  const [msg, setMsg] = useState<string | null>(null)
  const [reset, setReset] = useState(0)
  const [busy, setBusy] = useState(false)
  const desc = params.get('desc')

  async function submit(pin: string) {
    setBusy(true)
    try {
      await callJson('POST', '/api/auth/pin/verify', { pin })
      nav(safeNext(params.get('next')) ?? '/', { replace: true })
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      if (b.code === 'pin_locked') { await refresh(); return nav('/login', { replace: true }) }
      setMsg(b.message ?? '확인하지 못했어요.')
      setReset((n) => n + 1)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="auth-page center">
      <h2 className="auth-title">간편비밀번호를 입력해 주세요</h2>
      {desc && <p className="auth-notice">{desc}</p>}
      <p className="auth-sub">중요한 동작이라 한 번 더 확인해요.</p>
      {msg && <p className="auth-err" role="alert">{msg}</p>}
      <PinKeypad onComplete={(p) => void submit(p)} disabled={busy} resetKey={reset} />
      <button type="button" className="auth-link" onClick={() => nav(-1)}>취소</button>
    </section>
  )
}
