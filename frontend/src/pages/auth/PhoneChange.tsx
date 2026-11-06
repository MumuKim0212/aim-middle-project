import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiFail, callJson, firstFieldError } from '../../lib/http'

/** 휴대폰 번호 변경(S-05에서 진입). 형식은 가입 때와 같다(010으로 시작하는 숫자 10~11자리). 성공하면 내 정보로 돌아간다. */
export default function PhoneChange() {
  const nav = useNavigate()
  const [phone, setPhone] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await callJson('POST', '/api/me/phone', { phone })
      nav('/me', { replace: true, state: { flash: '휴대폰 번호를 변경했어요.' } })
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      setErr(firstFieldError(b)?.message ?? b.message ?? '변경하지 못했어요. 잠시 후 다시 해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="auth-page">
      <h2 className="auth-title">휴대폰 번호 변경</h2>
      <form className="auth-form" onSubmit={(e) => void submit(e)} noValidate>
        <label className="auth-field">새 휴대폰 번호
          <input inputMode="tel" value={phone} autoFocus autoComplete="tel" placeholder="010-0000-0000" onChange={(e) => { setPhone(e.target.value); setErr(null) }} />
          {err && <p className="auth-err" role="alert">{err}</p>}
        </label>
        <div className="auth-actions">
          <button type="button" className="ghost" onClick={() => nav('/me')}>취소</button>
          <button type="submit" className="primary" disabled={busy || !phone}>변경</button>
        </div>
      </form>
    </section>
  )
}
