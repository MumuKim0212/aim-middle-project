import { useState } from 'react'
import { Link } from 'react-router-dom'
import { won } from '../../format'
import { useLoad, type Product } from './api'
import { LoadState } from './parts'

const range = (lo: number | null, hi: number | null) => (lo === null || hi === null ? '제한 없음' : `${won(lo)} ~ ${won(hi)}`)

function amountText(p: Product) {
  if (p.type === 'checking') return '제한 없음'
  return p.type === 'savings' ? `월 ${range(p.minAmount, p.maxAmount)}` : range(p.minAmount, p.maxAmount)
}

const periodText = (p: Product) => p.type === 'checking' ? '없음' : p.minMonths === p.maxMonths ? `${p.maxMonths}개월 고정` : `${p.minMonths}~${p.maxMonths}개월`
const conditionText = (p: Product) => [p.requiresChecking ? '저축예금 보유' : '로그인한 누구나', p.maxPerUser ? `1인 최대 ${p.maxPerUser}개` : null].filter(Boolean).join(' · ')

/** A-02 상품 안내: 3종의 금리·기간·금액·가입 조건을 한 화면에서 비교한다(로그인 없이 조회). */
export default function Products() {
  const { data, error, reload } = useLoad<{ items: Product[] }>('/api/products')
  const [open, setOpen] = useState<number | null>(null)
  if (!data) return <LoadState error={error} retry={reload} />
  return (
    <section className="ac-page">
      <h2 className="auth-title">상품 안내</h2>
      <ul className="ac-products">
        {data.items.map((p) => (
          <li key={p.id} className="card">
            <div className="row"><strong>{p.name}</strong><span className="tag">연 {p.rate.toFixed(1)}%{p.type === 'checking' && ' (표시만)'}</span></div>
            <dl className="auth-summary">
              <div><dt>가입 금액</dt><dd>{amountText(p)}</dd></div>
              <div><dt>가입 기간</dt><dd>{periodText(p)}</dd></div>
              <div><dt>가입 조건</dt><dd>{conditionText(p)}</dd></div>
              {p.earlyCloseRate !== null && <div><dt>중도해지 금리</dt><dd>연 {p.earlyCloseRate.toFixed(1)}%</dd></div>}
            </dl>
            {open === p.id && <p className="ac-desc">{p.description}</p>}
            <div className="auth-actions">
              <button type="button" className="ghost" aria-expanded={open === p.id} onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? '접기' : '자세히'}</button>
              <Link to={`/products/${p.type}/open`} className="ac-link-btn">가입하기</Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
