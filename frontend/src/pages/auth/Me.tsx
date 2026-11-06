import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { callJson } from '../../lib/http'

type MeData = {
  user: { id: number; loginId: string; name: string; birthDate: string; phone: string; createdAt: string; lastLoginAt: string | null }
  deviceRegistered: boolean
  deviceName: string | null
}

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }) : '—')
const fmtPhone = (p: string) => p.replace(/^(\d{3})(\d{3,4})(\d{4})$/, '$1-$2-$3')

/** 내 정보(S-05): 가입 정보, 휴대폰 번호 변경, 간편비밀번호 변경, 이 기기 등록 해제, 로그아웃. */
export default function Me() {
  const nav = useNavigate()
  const { logout } = useAuth()
  const [data, setData] = useState<MeData | null>(null)
  const flash = (useLocation().state as { flash?: string } | null)?.flash
  const [msg, setMsg] = useState<string | null>(null)

  const load = () => { callJson<MeData>('GET', '/api/me').then(setData).catch(() => undefined) }
  useEffect(load, [])

  async function revoke() {
    await callJson('POST', '/api/auth/device/revoke')
    setMsg('이 기기의 간편 로그인을 해제했어요. 다음 로그인은 아이디와 비밀번호로 해 주세요.')
    load()
  }

  async function doLogout() {
    await logout()
    nav('/', { replace: true, state: { flash: '로그아웃되었습니다.' } })
  }

  if (!data) return <div className="state">불러오는 중…</div>
  const u = data.user
  return (
    <section className="auth-page">
      <h2 className="auth-title">내 정보</h2>
      <dl className="auth-summary">
        <div><dt>이름</dt><dd>{u.name}</dd></div>
        <div><dt>아이디</dt><dd>{u.loginId}</dd></div>
        <div><dt>생년월일</dt><dd>{u.birthDate}</dd></div>
        <div><dt>휴대폰 번호</dt><dd>{fmtPhone(u.phone)}</dd></div>
        <div><dt>가입일</dt><dd>{fmtDate(u.createdAt)}</dd></div>
        <div><dt>마지막 로그인</dt><dd>{fmtDate(u.lastLoginAt)}</dd></div>
        <div><dt>간편 로그인</dt><dd>{data.deviceRegistered ? `이 기기 등록됨 (${data.deviceName ?? ''})` : '이 기기는 등록되지 않았어요'}</dd></div>
      </dl>
      {(msg || flash) && <p className="auth-notice" role="status">{msg ?? flash}</p>}
      <div className="auth-stack">
        <Link to="/me/password" className="auth-btn">비밀번호 변경</Link>
        <Link to="/me/phone" className="auth-btn">휴대폰 번호 변경</Link>
        <Link to="/me/pin" className="auth-btn">간편비밀번호 변경</Link>
        {data.deviceRegistered && <button type="button" className="auth-btn" onClick={() => void revoke()}>이 기기 등록 해제</button>}
        <button type="button" className="auth-btn danger" onClick={() => void doLogout()}>로그아웃</button>
      </div>
    </section>
  )
}
