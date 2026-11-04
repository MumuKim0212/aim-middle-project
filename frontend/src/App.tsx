import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AccountPage from './features/account/AccountPage'
import CardPage from './features/card/CardPage'
import HomePage from './features/home/HomePage'
import LedgerPage from './features/ledger/LedgerPage'
import LoanPage from './features/loan/LoanPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="card" element={<CardPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="ledger" element={<LedgerPage />} />
        <Route path="loan" element={<LoanPage />} />
      </Route>
    </Routes>
  )
}
