import { Link } from 'react-router-dom'
import { koreanAmount, shortDate, won } from '../../format'
import { useLoad } from '../accounts/api'
import { STATUS_LABEL, type LoanProduct, type LoanSummary } from './api'
import { LoanLoad } from './parts'

/** 대출 조회·상품: 내 대출 목록(상세로 이동)과 대출 상품 안내(로그인 없이 볼 수 있는 상품 목록). 신청은 아직 없다. */
export default function LoanList() {
  const loans = useLoad<{ items: LoanSummary[] }>('/api/loans')
  const products = useLoad<{ items: LoanProduct[] }>('/api/loans/products')
  if (!loans.data || !products.data) return <LoanLoad error={loans.error ?? products.error} retry={() => { loans.reload(); products.reload() }} />

  return (
    <section className="ac-page">
      <div className="ac-group">
        <h3>내 대출</h3>
        {loans.data.items.length === 0
          ? <p className="ac-empty">받은 대출이 없어요.</p>
          : <ul>{loans.data.items.map((l) => <LoanCard key={l.contractNo} l={l} />)}</ul>}
      </div>
      <div className="ac-group">
        <h3>대출 상품</h3>
        <ul className="ac-products">{products.data.items.map((p) => <ProductCard key={p.productId} p={p} />)}</ul>
      </div>
    </section>
  )
}

function LoanCard({ l }: { l: LoanSummary }) {
  return (
    <li>
      <Link to={`/loans/${l.contractNo}`} className="ac-card">
        <div className="row">
          <strong>{l.productName}</strong>
          {l.status !== 'ACTIVE' && <span className="tag">{STATUS_LABEL[l.status]}</span>}
        </div>
        <p className="small">{l.accountMasked} · 연 {l.rate}%{l.nextDueDate && l.status === 'ACTIVE' && ` · 다음 상환일 ${shortDate(l.nextDueDate)}`}</p>
        <p className="ac-balance">{won(l.balance)}</p>
      </Link>
    </li>
  )
}

function ProductCard({ p }: { p: LoanProduct }) {
  return (
    <li className="card">
      <div className="row"><strong>{p.name}</strong><span className="tag">연 {p.rateMin}~{p.rateMax}%</span></div>
      <p className="small">{p.subtitle}</p>
      <dl className="auth-summary">
        <div><dt>대출 한도</dt><dd>{koreanAmount(p.minAmount)} ~ {koreanAmount(p.maxAmount)}</dd></div>
        <div><dt>대출 기간</dt><dd>{p.termOptions.join('·')}개월</dd></div>
        <div><dt>상환 방식</dt><dd>{p.repayOptions.join(', ')}</dd></div>
        <div><dt>대상</dt><dd>{p.targetDesc}</dd></div>
      </dl>
    </li>
  )
}
