import { Navigate, Route, Routes } from 'react-router-dom'
import { PublicOnly, RequireAuth } from './auth/guards'
import Layout from './components/Layout'
import AccountList from './features/accounts/AccountList'
import Close from './features/accounts/Close'
import Deposit from './features/accounts/Deposit'
import Detail, { Pay } from './features/accounts/Detail'
import Open from './features/accounts/Open'
import Products from './features/accounts/Products'
import Transactions from './features/accounts/Transactions'
import TransferFlow, { TransferDone, TransferStep1, TransferStep2, TransferStep3 } from './features/accounts/Transfer'
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
import LedgerPage from './features/ledger/LedgerPage'
import LoanDetail from './features/loans/Detail'
import LoanList from './features/loans/LoanList'
import LoanPrepay from './features/loans/Prepay'
import LoanSchedule from './features/loans/Schedule'
import Login from './pages/auth/Login'
import Me from './pages/auth/Me'
import PasswordChange from './pages/auth/PasswordChange'
import PhoneChange from './pages/auth/PhoneChange'
import PinSetup from './pages/auth/PinSetup'
import PinVerify from './pages/auth/PinVerify'
import Reset from './pages/auth/Reset'
import Signup from './pages/auth/Signup'
import Dashboard from './pages/Dashboard'
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

        <Route path="products" element={<Products />} />

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
          <Route path="home" element={<Dashboard />} />
          <Route path="me" element={<Me />} />
          <Route path="me/pin" element={<PinSetup />} />
          <Route path="me/password" element={<PasswordChange />} />
          <Route path="me/phone" element={<PhoneChange />} />
          <Route path="auth/pin/verify" element={<PinVerify />} />
          <Route path="accounts" element={<AccountList />} />
          <Route path="accounts/open" element={<Navigate to="/products" replace />} />
          <Route path="accounts/:id" element={<Detail />} />
          <Route path="accounts/:id/transactions" element={<Transactions />} />
          <Route path="accounts/:id/deposit" element={<Deposit />} />
          <Route path="accounts/:id/pay" element={<Pay />} />
          <Route path="accounts/:id/close" element={<Close />} />
          <Route path="products/:type/open" element={<Open />} />
          <Route path="transfer" element={<TransferFlow />}>
            <Route index element={<TransferStep1 />} />
            <Route path="amount" element={<TransferStep2 />} />
            <Route path="confirm" element={<TransferStep3 />} />
            <Route path="done" element={<TransferDone />} />
          </Route>
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
          <Route path="loans" element={<LoanList />} />
          <Route path="loans/:no" element={<LoanDetail />} />
          <Route path="loans/:no/schedule" element={<LoanSchedule />} />
          <Route path="loans/:no/prepay" element={<LoanPrepay />} />
          <Route path="ledger" element={<LedgerPage />} />
          <Route path="ledger/:tab" element={<LedgerPage />} />
        </Route>

        <Route path="auth/reset" element={<Reset />} />
        <Route path="*" element={<Placeholder title="페이지를 찾을 수 없어요" />} />
      </Route>
    </Routes>
  )
}
