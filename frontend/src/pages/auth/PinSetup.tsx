import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import PinKeypad from '../../auth/PinKeypad'
import { ApiFail, callJson, safeNext } from '../../lib/http'

type Step = 'current' | 'new' | 'confirm'

/**
 * 간편비밀번호 설정(S-07).
 *  · 가입 직후·미설정·잠김 상태(pinSetupRequired): 건너뛸 수 없다. 새 6자리를 두 번 입력.
 *  · 이미 쓰는 사람(/me/pin): 현재 6자리를 먼저 확인한 뒤 새 6자리를 두 번 입력.
 * 규칙(같은 숫자·연속 숫자·생년월일)은 서버가 판단하고, 이 화면은 메시지만 보여 준다.
 */
export default function PinSetup() {
  const { state, refresh } = useAuth()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const change = !state.pinSetupRequired // 이미 설정된 사람이 바꾸는 경우
  const [step, setStep] = useState<Step>(change ? 'current' : 'new')
  const [cur, setCur] = useState('')
  const [first, setFirst] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [reset, setReset] = useState(0)
  const [busy, setBusy] = useState(false)

  const redo = (m: string, to: Step) => { setMsg(m); setStep(to); setReset((n) => n + 1) }

  async function onPin(pin: string) {
    setMsg(null)
    if (step === 'current') { setCur(pin); setStep('new'); setReset((n) => n + 1); return }
    if (step === 'new') { setFirst(pin); setStep('confirm'); setReset((n) => n + 1); return }
    setBusy(true)
    try {
      await callJson('POST', '/api/auth/pin/setup', { pin: first, pinConfirm: pin, currentPin: change ? cur : undefined })
      await refresh()
      nav(safeNext(params.get('next')) ?? (change ? '/me' : '/home'), { replace: true })
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      if (b.code === 'pin_invalid' || b.code === 'current_secret_invalid') redo(b.message ?? '현재 간편비밀번호가 맞지 않아요.', 'current')
      else if (b.code === 'pin_locked') { await refresh(); nav('/login', { replace: true }) }
      else redo(b.message ?? '설정하지 못했어요. 다시 입력해 주세요.', 'new')
    } finally {
      setBusy(false)
    }
  }

  const title = step === 'current' ? '현재 간편비밀번호를 입력해 주세요' : step === 'new' ? '앞으로 이 6자리로 로그인해요' : '한 번 더 입력해 주세요'
  const sub = step === 'new' ? '같은 숫자, 연속된 숫자, 생년월일은 쓸 수 없어요.' : step === 'confirm' ? '방금 입력한 번호와 같아야 해요.' : ''

  return (
    <section className="auth-page center">
      <h2 className="auth-title">{title}</h2>
      {sub && <p className="auth-sub">{sub}</p>}
      {state.pinSetupRequired && step === 'new' && <p className="auth-notice">처음 한 번만 설정하면 돼요. 이 단계는 건너뛸 수 없어요.</p>}
      {msg && <p className="auth-err" role="alert">{msg}</p>}
      <PinKeypad onComplete={(p) => void onPin(p)} disabled={busy} resetKey={reset} />
      {change && <button type="button" className="auth-link" onClick={() => nav('/me')}>취소</button>}
    </section>
  )
}
