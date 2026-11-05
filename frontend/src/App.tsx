import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Placeholder from './pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="accounts" element={<Placeholder title="계좌" owner="김연준" />} />
        <Route path="accounts/open" element={<Placeholder title="계좌개설" owner="김연준" />} />
        <Route path="auth/reset" element={<Placeholder title="로그인 · 비밀번호 재설정" />} />
        <Route path="auth/login" element={<Placeholder title="로그인" />} />
        <Route path="cards" element={<Placeholder title="카드" owner="김경민" />} />
        <Route path="loans" element={<Placeholder title="대출" owner="임대진" />} />
        <Route path="ledger" element={<Placeholder title="가계부" owner="박의혁" />} />
        <Route path="*" element={<Placeholder title="페이지를 찾을 수 없어요" />} />
      </Route>
    </Routes>
  )
}
