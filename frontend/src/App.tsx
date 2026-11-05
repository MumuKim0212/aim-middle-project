import { Route, Routes } from 'react-router-dom'
import { PublicOnly, RequireAuth } from './auth/guards'
import Layout from './components/Layout'
import LedgerPage from './features/ledger/LedgerPage'
import Login from './pages/auth/Login'
import Me from './pages/auth/Me'
import PasswordChange from './pages/auth/PasswordChange'
import PinSetup from './pages/auth/PinSetup'
import PinVerify from './pages/auth/PinVerify'
import Reset from './pages/auth/Reset'
import Signup from './pages/auth/Signup'
import Home from './pages/Home'
import Placeholder from './pages/Placeholder'

/**
 * 접근 규칙(회원·인증 기획서 R1·R2·R10):
 *  · 로그인 없이: 시작(/), 회원가입(/signup/*), 로그인(/login*)
 *  · 로그인 필요: 그 밖의 모든 화면. 미인증이면 /login?next=… 로, 간편비밀번호가 없으면 /auth/pin/setup 으로 보낸다.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />

        <Route element={<PublicOnly />}>
          <Route path="login" element={<Login />} />
          <Route path="login/password" element={<Login />} />
          <Route path="signup" element={<Signup />} />
          <Route path="signup/:step" element={<Signup />} />
        </Route>

        {/* 간편비밀번호 설정은 설정 전(pin_setup_required)에도 들어올 수 있다 */}
        <Route element={<RequireAuth allowSetup />}>
          <Route path="auth/pin/setup" element={<PinSetup />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route path="me" element={<Me />} />
          <Route path="me/pin" element={<PinSetup />} />
          <Route path="me/password" element={<PasswordChange />} />
          <Route path="auth/pin/verify" element={<PinVerify />} />
          <Route path="accounts" element={<Placeholder title="계좌" owner="김연준" />} />
          <Route path="accounts/open" element={<Placeholder title="계좌개설" owner="김연준" />} />
          <Route path="cards" element={<Placeholder title="카드" owner="김경민" />} />
          <Route path="loans" element={<Placeholder title="대출" owner="임대진" />} />
          <Route path="ledger" element={<LedgerPage />} />
          <Route path="ledger/:tab" element={<LedgerPage />} />
        </Route>

        <Route path="auth/reset" element={<Reset />} />
        <Route path="*" element={<Placeholder title="페이지를 찾을 수 없어요" />} />
      </Route>
    </Routes>
  )
}
