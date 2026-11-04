import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AccountPage from './features/account/AccountPage'
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
import HomePage from './features/home/HomePage'
import LedgerPage from './features/ledger/LedgerPage'
import LoanPage from './features/loan/LoanPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        {/* shortcut: 로그인 가드(RequireAuth)는 아직 없다. 로그인 담당이 정해지면 card 라우트에 건다. */}
        <Route path="card">
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
        <Route path="account" element={<AccountPage />} />
        <Route path="ledger" element={<LedgerPage />} />
        <Route path="loan" element={<LoanPage />} />
      </Route>
    </Routes>
  )
}
