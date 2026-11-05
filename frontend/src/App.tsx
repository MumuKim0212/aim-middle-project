import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import CardShell from './features/card/components/CardShell'
import ApplyPage from './features/card/pages/ApplyPage'
import ApplyResultPage from './features/card/pages/ApplyResultPage'
import BillingPage from './features/card/pages/BillingPage'
import CardDetailPage from './features/card/pages/CardDetailPage'
import CardListPage from './features/card/pages/CardListPage'
import CardPickerPage from './features/card/pages/CardPickerPage'
import LimitPage from './features/card/pages/LimitPage'
import SecurityPage from './features/card/pages/SecurityPage'
import TerminatePage from './features/card/pages/TerminatePage'
import TransactionsPage from './features/card/pages/TransactionsPage'
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
        <Route path="cards" element={<CardShell />}>
          <Route index element={<CardListPage />} />
          <Route path="transactions" element={<TransactionsPage />} />
          <Route path="billing" element={<BillingPage />} />
          <Route path="security" element={<CardPickerPage purpose="security" />} />
          <Route path="limit" element={<CardPickerPage purpose="limit" />} />
          <Route path="apply" element={<ApplyPage />} />
          <Route path="apply/result" element={<ApplyResultPage />} />
          <Route path=":cardId" element={<CardDetailPage />} />
          <Route path=":cardId/security" element={<SecurityPage />} />
          <Route path=":cardId/limit" element={<LimitPage />} />
          <Route path=":cardId/terminate" element={<TerminatePage />} />
        </Route>
        <Route path="loans" element={<Placeholder title="대출" owner="임대진" />} />
        <Route path="ledger" element={<Placeholder title="가계부" owner="박의혁" />} />
        <Route path="*" element={<Placeholder title="페이지를 찾을 수 없어요" />} />
      </Route>
    </Routes>
  )
}
