import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { dDay, shortDate, won } from '../../format'
import { accountName, TYPE_LABEL, useLoad, type Account, type ProductType } from './api'
import { LoadState } from './parts'

type List = { totalBalance: number; items: Account[] }
const ORDER: ProductType[] = ['checking', 'deposit', 'savings']

/** A-01 계좌 목록: 총 잔액, 종류별 계좌 카드, 대표계좌 표시, 해지된 계좌는 따로. */
export default function AccountList() {
  const [closed, setClosed] = useState(false)
  const { data, error, reload } = useLoad<List>(closed ? '/api/accounts?status=closed' : '/api/accounts')
  const flash = (useLocation().state as { flash?: string } | null)?.flash
  if (!data) return <LoadState error={error} retry={reload} />

  return (
    <section className="ac-page">
      {flash && <p className="auth-flash" role="status">{flash}</p>}
      {!closed && (
        <div className="ac-total">
          <p className="label">내 계좌 총 잔액</p>
          <p className="big">{won(data.totalBalance)}</p>
          <div className="ac-quick">
            <Link to="/transfer">이체</Link>
            <Link to="/products">계좌 개설</Link>
            <Link to="/products">상품 안내</Link>
          </div>
        </div>
      )}
      {data.items.length === 0 && (
        <div className="ac-empty">
          <p>{closed ? '해지된 계좌가 없어요.' : '아직 계좌가 없어요.'}</p>
          {!closed && <Link to="/products/checking/open" className="auth-btn">첫 계좌 만들기</Link>}
        </div>
      )}
      {(closed ? [null] : ORDER).map((t) => {
        const rows = data.items.filter((a) => t === null || a.productType === t)
        if (!rows.length) return null
        return (
          <div key={t ?? 'closed'} className="ac-group">
            <h3>{t ? TYPE_LABEL[t] : '해지된 계좌'}</h3>
            <ul>{rows.map((a) => <AccountCard key={a.accountId} a={a} />)}</ul>
          </div>
        )
      })}
      <button type="button" className="auth-link" onClick={() => setClosed((c) => !c)}>{closed ? '사용 중인 계좌 보기' : '해지된 계좌 보기'}</button>
    </section>
  )
}

function AccountCard({ a }: { a: Account }) {
  const d = a.maturityDate && a.status === 'active' ? dDay(a.maturityDate) : null
  return (
    <li>
      <Link to={`/accounts/${a.accountId}`} className="ac-card">
        <div className="row">
          <strong>{accountName(a)}{a.isPrimary && <em className="chip-mini ac-primary">대표</em>}</strong>
          {a.status !== 'active' && <span className="tag">{STATUS[a.status]}</span>}
          {d !== null && <span className="tag">{d > 0 ? `만기 D-${d}` : d === 0 ? '오늘 만기' : '만기 도래'}</span>}
        </div>
        <p className="small">{a.bankName} {a.accountMasked}{a.maturityDate && ` · 만기 ${shortDate(a.maturityDate)}`}</p>
        <p className="ac-balance">{won(a.balance)}</p>
      </Link>
    </li>
  )
}

export const STATUS: Record<Account['status'], string> = { active: '사용 중', matured: '만기해지', closed_early: '중도해지', closed: '해지' }
