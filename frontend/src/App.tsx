import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import LedgerPage from './features/ledger/LedgerPage'
import Placeholder from './pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="accounts" element={<Placeholder title="계좌" owner="김연준" />} />
        <Route path="cards" element={<Placeholder title="카드" owner="김경민" />} />
        <Route path="loans" element={<Placeholder title="대출" owner="임대진" />} />
        <Route path="ledger" element={<LedgerPage />} />
        <Route path="*" element={<Placeholder title="페이지를 찾을 수 없어요" />} />
      </Route>
    </Routes>
  )
}
