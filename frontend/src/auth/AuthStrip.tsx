import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

/** 시작 화면 위쪽: 로그인 전엔 로그인·회원가입, 후엔 인사와 내 정보·로그아웃. 로그아웃 직후 안내도 여기서 보여 준다. */
export default function AuthStrip() {
  const { state, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const flash = (loc.state as { flash?: string } | null)?.flash
  if (state.loading) return null
  return (
    <>
      {flash && <p className="auth-flash" role="status">{flash}</p>}
      {state.authenticated && state.user ? (
        <div className="auth-strip">
          <span><strong>{state.user.name}님</strong> 환영해요</span>
          <span className="btns">
            <Link to="/home">내 금융</Link>
            <Link to="/me" className="ghost">내 정보</Link>
            <button type="button" onClick={async () => { await logout(); nav('/', { replace: true, state: { flash: '로그아웃되었습니다.' } }) }}>로그아웃</button>
          </span>
        </div>
      ) : (
        <div className="auth-strip">
          <span>로그인하고 내 금융을 확인해 보세요</span>
          <span className="btns"><Link to="/login">로그인</Link><Link to="/signup/1" className="ghost">회원가입</Link></span>
        </div>
      )}
    </>
  )
}
