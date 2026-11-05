import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import PinKeypad from '../../auth/PinKeypad'
import { ApiFail, callJson, safeNext } from '../../lib/http'

type DeviceInfo = { registered: boolean; name?: string; pinLocked?: boolean; remaining?: number }

/** /login: 이 브라우저가 등록돼 있으면 간편 로그인(S-03a), 아니면 아이디·비밀번호(S-03b). /login/password 는 항상 S-03b. */
export default function Login() {
  const loc = useLocation()
  const [params] = useSearchParams()
  const [dev, setDev] = useState<DeviceInfo | null>(null)
  const [forcePassword, setForcePassword] = useState(loc.pathname === '/login/password')
  const [notice, setNotice] = useState<string | null>(params.get('expired') ? '로그인 시간이 만료되었습니다. 다시 로그인해 주세요.' : null)

  useEffect(() => {
    callJson<DeviceInfo>('GET', '/api/auth/device').then(setDev).catch(() => setDev({ registered: false }))
  }, [])

  if (!dev) return <div className="state">불러오는 중…</div>
  const usePin = dev.registered && !dev.pinLocked && !forcePassword
  const lockedNotice = dev.registered && dev.pinLocked ? '간편비밀번호가 잠겼습니다. 아이디와 비밀번호로 로그인해 주세요.' : null

  return usePin ? (
    <PinLogin dev={dev} notice={notice} onOther={() => { setNotice(null); setForcePassword(true) }}
      onFallback={(msg) => { setNotice(msg); setForcePassword(true) }} />
  ) : (
    <PasswordLogin notice={notice ?? lockedNotice} />
  )
}

function useAfterLogin() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const { refresh } = useAuth()
  return async () => {
    await refresh()
    nav(safeNext(params.get('next')) ?? '/home', { replace: true })
  }
}

function PinLogin({ dev, notice, onOther, onFallback }: { dev: DeviceInfo; notice: string | null; onOther: () => void; onFallback: (m: string) => void }) {
  const after = useAfterLogin()
  const [msg, setMsg] = useState<string | null>(null)
  const [reset, setReset] = useState(0)
  const [busy, setBusy] = useState(false)

  async function submit(pin: string) {
    setBusy(true)
    try {
      await callJson('POST', '/api/auth/pin/login', { pin })
      await after()
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      if (b.code === 'PIN_LOCKED' || b.code === 'DEVICE_INVALID') return onFallback(b.message ?? '아이디와 비밀번호로 로그인해 주세요.')
      setMsg(b.message ?? '로그인하지 못했어요.')
      setReset((n) => n + 1)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="auth-page center">
      <h2 className="auth-title">{dev.name}님, 안녕하세요</h2>
      <p className="auth-sub">간편비밀번호 6자리를 입력해 주세요.</p>
      {notice && <p className="auth-notice" role="status">{notice}</p>}
      {msg && <p className="auth-err" role="alert">{msg}</p>}
      <PinKeypad onComplete={(p) => void submit(p)} disabled={busy} resetKey={reset} />
      <button type="button" className="auth-link" onClick={onOther}>다른 방법으로 로그인</button>
    </section>
  )
}

function PasswordLogin({ notice }: { notice: string | null }) {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const { refresh } = useAuth()
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [askDevice, setAskDevice] = useState(false)
  const next = safeNext(params.get('next'))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      const r = await callJson<{ pinSetupRequired: boolean; canRegisterDevice: boolean }>('POST', '/api/auth/login', { loginId, password })
      // 기기 등록 질문을 먼저 보여 줘야 해서, 그 경우에는 답한 뒤에 로그인 상태를 갱신한다(갱신하면 이 화면이 바로 닫힌다)
      if (r.canRegisterDevice && !r.pinSetupRequired) return setAskDevice(true)
      await refresh()
      if (r.pinSetupRequired) return nav(next ? `/auth/pin/setup?next=${encodeURIComponent(next)}` : '/auth/pin/setup', { replace: true })
      nav(next ?? '/home', { replace: true })
    } catch (x) {
      setErr(x instanceof ApiFail ? x.message : '로그인하지 못했어요. 잠시 후 다시 해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  async function answer(yes: boolean) {
    if (yes) await callJson('POST', '/api/auth/device/register').catch(() => undefined)
    await refresh()
    nav(next ?? '/home', { replace: true })
  }

  return (
    <section className="auth-page">
      <h2 className="auth-title">로그인</h2>
      {notice && <p className="auth-notice" role="status">{notice}</p>}
      <form className="auth-form" onSubmit={(e) => void submit(e)}>
        <label className="auth-field">아이디
          <input value={loginId} autoFocus autoCapitalize="none" autoComplete="username" onChange={(e) => setLoginId(e.target.value)} />
        </label>
        <label className="auth-field">비밀번호
          <input type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
        </label>
        {err && <p className="auth-err" role="alert">{err}</p>}
        <div className="auth-actions"><button type="submit" className="primary" disabled={busy || !loginId || !password}>로그인</button></div>
      </form>
      <p className="auth-foot">아직 회원이 아니신가요? <Link to="/signup/1">회원가입</Link></p>

      {askDevice && (
        <div className="auth-modal" role="dialog" aria-modal="true" aria-label="기기 등록">
          <div>
            <h3>이 기기에서 간편 로그인을 사용할까요?</h3>
            <p>다음부터 간편비밀번호 6자리만 입력하면 로그인돼요. 내 기기에서만 사용해 주세요.</p>
            <div className="auth-actions">
              <button type="button" className="ghost" onClick={() => void answer(false)}>아니오</button>
              <button type="button" className="primary" onClick={() => void answer(true)}>예</button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
