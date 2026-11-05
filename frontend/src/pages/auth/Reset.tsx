import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'

/**
 * /auth/reset — "로그인·비밀번호 재설정".
 *  · 로그인한 사람: 비밀번호 변경 화면(/me/password)으로 보낸다.
 *  · 로그인 전: 이 프로젝트는 메일·본인인증이 없어서 비밀번호 찾기를 지원하지 않는다(기획서 3.2). 할 수 있는 일을 안내한다.
 */
export default function Reset() {
  const { state } = useAuth()
  if (state.loading) return <div className="state">불러오는 중…</div>
  if (state.authenticated) return <Navigate to={state.pinSetupRequired ? '/auth/pin/setup' : '/me/password'} replace />

  return (
    <section className="auth-page">
      <h2 className="auth-title">로그인·비밀번호 재설정</h2>
      <div className="auth-help">
        <h3>비밀번호를 바꾸고 싶어요</h3>
        <p>로그인한 뒤 <b>내 정보 → 비밀번호 변경</b>에서 바꿀 수 있어요.</p>
        <Link to="/login?next=%2Fme%2Fpassword" className="auth-btn">로그인하고 변경하기</Link>
      </div>
      <div className="auth-help">
        <h3>간편비밀번호가 잠겼어요</h3>
        <p>아이디와 비밀번호로 로그인하면 간편비밀번호를 새로 설정할 수 있어요.</p>
        <Link to="/login/password" className="auth-btn">아이디·비밀번호로 로그인</Link>
      </div>
      <div className="auth-help">
        <h3>비밀번호를 잊어버렸어요</h3>
        <p>이 서비스는 메일이나 본인인증이 없어서 비밀번호를 찾아 드릴 수 없어요. 새 계정을 만들어 이용해 주세요.</p>
        <Link to="/signup/1" className="auth-btn">회원가입</Link>
      </div>
    </section>
  )
}
