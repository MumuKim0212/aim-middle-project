import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchHome, type HomeData, type LoanProduct } from '../api'
import { fetchSummary, type Summary } from '../features/ledger/api'
import { dDay, koreanAmount, shortDate, won } from '../format'

type Filter = 'all' | LoanProduct['type']
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'general', label: '일반대출' },
  { key: 'gov', label: '정부대출' },
  { key: 'org', label: '기관대출' },
  { key: 'refi', label: '대환' },
]
const ICONS: Record<string, string> = { card: '💳', home: '🏠', key: '🔑', shield: '🛡️', swap: '🔁' }

/** 로그인 후 홈(S-04): 인사·계좌·대출·가계부·카드 요약. 로그인한 사용자의 데이터만 보인다. */
export default function Dashboard() {
  const [data, setData] = useState<HomeData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchHome().then(setData).catch((e: Error) => setError(e.message))
  }, [])

  if (error) {
    return (
      <div className="state">
        <p>데이터를 불러오지 못했어요.</p>
        <small>{error} · 백엔드가 켜져 있는지 확인하세요.</small>
      </div>
    )
  }
  if (!data) return <div className="state">불러오는 중…</div>

  return (
    <div className="dash">
      <Greeting data={data} />
      <PromoBanner />
      <QuickMenu />
      <MyLoans data={data} />
      <SummaryRow data={data} />
      <LoanProducts products={data.loans.products} />
    </div>
  )
}

/* 인사말 + 총자산 + 계좌 */
function Greeting({ data }: { data: HomeData }) {
  return (
    <section className="asset-card">
      <p className="hello">{data.user.name}님, 안녕하세요</p>
      <p className="label">내 계좌 총 잔액</p>
      <p className="big">{won(data.accounts.totalBalance)}</p>
      <ul className="acc-list">
        {data.accounts.items.map((a) => (
          <li key={a.id}>
            <span>
              {a.bankName} {a.masked}
              {a.primary && <em className="chip-mini">대표</em>}
            </span>
            <b>{won(a.balance)}</b>
          </li>
        ))}
      </ul>
    </section>
  )
}

/* 대출 프로모션 배너 (시안의 큰 카드) */
function PromoBanner() {
  return (
    <section className="promo">
      <div>
        <h2>
          직장인 전용
          <br />
          비대면 신용대출
        </h2>
        <Link to="/loans" className="promo-link">
          OO 직장인 신용대출 ›
        </Link>
        <p className="max">
          <span className="badge">최대</span> 1억원
        </p>
      </div>
      <div className="promo-art" aria-hidden>
        🧮
      </div>
      <div className="dots" aria-hidden>
        <i className="on" />
        <i />
        <i />
      </div>
    </section>
  )
}

function QuickMenu() {
  const items = [
    { to: '/accounts', icon: '💳', label: '계좌' },
    { to: '/cards', icon: '🪪', label: '카드' },
    { to: '/loans', icon: '🏦', label: '대출' },
    { to: '/ledger', icon: '📒', label: '가계부' },
  ]
  return (
    <section className="quick">
      {items.map((i) => (
        <Link key={i.to} to={i.to}>
          <span className="q-ico">{i.icon}</span>
          {i.label}
        </Link>
      ))}
    </section>
  )
}

/* 내 대출 한눈에 (대출관리 대시보드 시안) */
function MyLoans({ data }: { data: HomeData }) {
  const { loans } = data
  if (loans.count === 0) return null
  const d = loans.nextDueDate ? dDay(loans.nextDueDate) : null
  return (
    <section className="card">
      <div className="loan-hero">
        <div>
          <p className="label">내 대출 총 잔액 · {loans.count}건</p>
          <p className="big blue">{koreanAmount(loans.totalBalance)}</p>
        </div>
        <span className="cal" aria-hidden>
          🗓️
        </span>
      </div>
      <div className="two">
        <div className="mini">
          <small>다음 납입일</small>
          <b>
            {loans.nextDueDate ? shortDate(loans.nextDueDate) : '-'}
            {d !== null && <em> (D-{d})</em>}
          </b>
        </div>
        <div className="mini">
          <small>이번 달 납입액</small>
          <b>{won(loans.nextDueAmount)}</b>
        </div>
      </div>
      {loans.items.map((l) => {
        const repaid = Math.round((1 - l.balance / l.amount) * 100)
        return (
          <article className="loan-item" key={l.contractNo}>
            <div className="row">
              <strong>{l.productName}</strong>
              <span className="tag ok">정상</span>
            </div>
            <small className="muted">{l.contractNo}</small>
            <p className="row">
              <span className="muted">잔액</span>
              <b>{koreanAmount(l.balance)}</b>
            </p>
            <div className="bar" role="progressbar" aria-valuenow={repaid} aria-valuemin={0} aria-valuemax={100}>
              <i style={{ width: `${repaid}%` }} />
            </div>
            <p className="row small">
              <span>상환 {repaid}%</span>
              <span>연 {l.rate.toFixed(2)}%</span>
            </p>
          </article>
        )
      })}
    </section>
  )
}

/* 가계부 · 카드 요약 */
function SummaryRow({ data }: { data: HomeData }) {
  const { cards } = data
  return (
    <section className="two-cards">
      <LedgerCard />
      <Link to="/cards" className="card compact">
        <p className="label">이번 달 카드 사용</p>
        <p className="mid">{won(cards.monthSpent)}</p>
        <small className="muted">보유 카드 {cards.count}장</small>
        <div className="card-dots">
          {cards.items.map((c) => (
            <span key={c.id} className="tag">
              {c.type === 'credit' ? '신용' : '체크'} {c.last4}
            </span>
          ))}
        </div>
      </Link>
    </section>
  )
}

/** 가계부 카드: 가계부 화면과 같은 값(남은 예산·오늘 쓸 수 있는 돈)을 보여 주고 누르면 가계부로 간다 */
function LedgerCard() {
  const [s, setS] = useState<Summary | null>(null)
  useEffect(() => {
    fetchSummary().then(setS).catch(() => undefined)
  }, [])
  if (!s) return <Link to="/ledger" className="card compact"><p className="label">가계부</p><small className="muted">불러오는 중…</small></Link>
  const b = s.budget
  return (
    <Link to="/ledger" className="card compact">
      <p className="label">{Number(s.month.slice(5))}월 가계부</p>
      <p className="mid">{won(b.remaining)}</p>
      <small className="muted">남은 예산</small>
      <div className="bar thin">
        <i style={{ width: `${Math.min(100, Math.max(0, b.ratio))}%` }} />
      </div>
      <small className="muted">
        {won(b.spent)} / {won(b.total)}
      </small>
      {s.daily && (
        <div className="card-dots">
          <span className="tag">{s.daily.left < 0 ? '오늘 한도 초과' : `오늘 ${won(s.daily.left)}`}</span>
          {s.risk.level !== 'safe' && <span className="tag ok" style={{ background: '#fff2eb', color: '#af593c' }}>예산 {s.risk.level === 'danger' ? '경고' : '주의'}</span>}
        </div>
      )}
    </Link>
  )
}

/* 대출 상품 목록 (칩 필터 + 리스트) */
function LoanProducts({ products }: { products: LoanProduct[] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const list = products.filter((p) => filter === 'all' || p.type === filter)
  return (
    <section className="products">
      <h3>대출 상품</h3>
      <div className="chips" role="tablist">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            role="tab"
            aria-selected={filter === f.key}
            className={filter === f.key ? 'chip on' : 'chip'}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <ul>
        {list.map((p) => (
          <li key={p.id} className="product">
            <div className="p-body">
              <div className="p-tags">
                {p.tags.map((t) => (
                  <span key={t} className="tag">
                    {t}
                  </span>
                ))}
              </div>
              <strong>{p.name}</strong>
              <small className="muted">
                최대 <b>{p.maxAmount ? koreanAmount(p.maxAmount) : '-'}</b> | 기간 {p.term ?? '-'}
              </small>
            </div>
            <span className="p-ico" aria-hidden>
              {ICONS[p.icon ?? ''] ?? '🏦'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
