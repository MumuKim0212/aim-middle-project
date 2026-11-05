import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiFail, callJson, firstFieldError } from '../../lib/http'

/** 비밀번호 변경(S-06): 현재 비밀번호 확인 → 새 비밀번호(가입 때와 같은 규칙). 성공하면 내 정보로 돌아간다. */
export default function PasswordChange() {
  const nav = useNavigate()
  const [cur, setCur] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [revoke, setRevoke] = useState(false)
  const [err, setErr] = useState<{ field?: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await callJson('POST', '/api/auth/password/change', { currentPassword: cur, newPassword: pw, newPasswordConfirm: pw2, revokeOtherDevices: revoke })
      nav('/me', { replace: true, state: { flash: '비밀번호를 변경했어요.' } })
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      const fe0 = firstFieldError(b)
      const field = fe0?.field ?? (b.code === 'CURRENT_PASSWORD_INVALID' ? 'currentPassword' : undefined)
      setErr({ field, message: fe0?.message ?? b.message ?? '변경하지 못했어요. 잠시 후 다시 해 주세요.' })
    } finally {
      setBusy(false)
    }
  }

  const fe = (k: string) => (err?.field === k ? <p className="auth-err" role="alert">{err.message}</p> : null)

  return (
    <section className="auth-page">
      <h2 className="auth-title">비밀번호 변경</h2>
      <form className="auth-form" onSubmit={(e) => void submit(e)} noValidate>
        <label className="auth-field">현재 비밀번호
          <input type="password" value={cur} autoFocus autoComplete="current-password" onChange={(e) => { setCur(e.target.value); setErr(null) }} />
          {fe('currentPassword')}
        </label>
        <label className="auth-field">새 비밀번호
          <input type="password" value={pw} autoComplete="new-password" placeholder="8~20자, 영문·숫자·특수문자 중 2종류 이상" onChange={(e) => { setPw(e.target.value); setErr(null) }} />
          {fe('newPassword')}
        </label>
        <label className="auth-field">새 비밀번호 확인
          <input type="password" value={pw2} autoComplete="new-password" onChange={(e) => { setPw2(e.target.value); setErr(null) }} />
          {fe('newPasswordConfirm')}
        </label>
        <label className="auth-check"><input type="checkbox" checked={revoke} onChange={(e) => setRevoke(e.target.checked)} /> 다른 기기의 간편 로그인 등록도 해제할게요</label>
        {err && !err.field && <p className="auth-err" role="alert">{err.message}</p>}
        <div className="auth-actions">
          <button type="button" className="ghost" onClick={() => nav('/me')}>취소</button>
          <button type="submit" className="primary" disabled={busy || !cur || !pw || !pw2}>변경</button>
        </div>
      </form>
    </section>
  )
}
