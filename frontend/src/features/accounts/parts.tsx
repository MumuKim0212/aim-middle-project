import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import PinKeypad from '../../auth/PinKeypad'
import { won } from '../../format'
import { ApiFail, callJson } from '../../lib/http'
import { errCode, hangulAmount } from './api'
import './accounts.css'

/** 로딩 · 불러오기 실패(다시 시도) · 없는 계좌(404, S-10)를 한곳에서 보여 준다. */
export function LoadState({ error, retry }: { error: unknown; retry: () => void }) {
  if (error && errCode(error) === 'ACCOUNT_NOT_FOUND') return <div className="state">페이지를 찾을 수 없어요.</div>
  if (error) return <div className="state">불러오지 못했어요.<br /><button type="button" className="ac-retry" onClick={retry}>다시 시도</button></div>
  return <div className="state">불러오는 중…</div>
}

export function Steps({ now, total }: { now: number; total: number }) {
  return <div className="auth-progress" aria-label={`${total}단계 중 ${now}단계`}><span>{now}/{total}</span><i style={{ width: `${(now / total) * 100}%` }} /></div>
}

/** 금액 입력(숫자 키패드). 입력 중인 금액과 한글 금액(일만원)을 함께 보여 준다. value 는 숫자만 담은 문자열. */
export function AmountField({ value, onChange, max = 9_999_999_999, hint }: { value: string; onChange: (v: string) => void; max?: number; hint?: ReactNode }) {
  const n = Number(value || 0)
  function press(k: string) {
    if (k === '⌫') return onChange(value.slice(0, -1))
    const next = (value + k).replace(/^0+/, '')
    if (Number(next || 0) <= max) onChange(next)
  }
  return (
    <div className="ac-amount">
      <p className="ac-amount-won" aria-live="polite">{n ? won(n) : '금액을 입력해 주세요'}</p>
      <p className="ac-amount-ko">{hangulAmount(n) || ' '}</p>
      {hint && <p className="ac-amount-hint">{hint}</p>}
      <div className="pin-pad" role="group" aria-label="숫자 키패드">
        {['1', '2', '3', '4', '5', '6', '7', '8', '9', '00', '0', '⌫'].map((k) => (
          <button key={k} type="button" aria-label={k === '⌫' ? '지우기' : k} onClick={() => press(k)}>{k}</button>
        ))}
      </div>
    </div>
  )
}

/** 본인 재확인(S-08) 팝업. 다단계 입력 도중 화면을 벗어나지 않으려고 PinKeypad 로 직접 /api/auth/pin/verify 를 부른다(공통.md 4장). */
export function PinDialog({ desc, onVerified, onCancel }: { desc: string; onVerified: () => void; onCancel: () => void }) {
  const nav = useNavigate()
  const { refresh } = useAuth()
  const [msg, setMsg] = useState<string | null>(null)
  const [reset, setReset] = useState(0)
  const [busy, setBusy] = useState(false)

  async function submit(pin: string) {
    setBusy(true)
    try {
      await callJson('POST', '/api/auth/pin/verify', { pin })
      onVerified()
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      if (b.code === 'PIN_LOCKED') { await refresh(); return nav('/login', { replace: true }) }
      setMsg(b.message ?? '확인하지 못했어요.')
      setReset((r) => r + 1)
    } finally { setBusy(false) }
  }

  return (
    <div className="auth-modal" role="dialog" aria-modal="true" aria-label="간편비밀번호 확인">
      <div className="ac-pin">
        <h3>간편비밀번호를 입력해 주세요</h3>
        <p>{desc}</p>
        {msg && <p className="auth-err" role="alert">{msg}</p>}
        <PinKeypad onComplete={(p) => void submit(p)} disabled={busy} resetKey={reset} />
        <button type="button" className="auth-link" onClick={onCancel}>취소</button>
      </div>
    </div>
  )
}
