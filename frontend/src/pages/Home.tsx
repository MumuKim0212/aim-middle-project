import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import AuthStrip from '../auth/AuthStrip'
import './home.css'

type Pictogram = 'open' | 'account' | 'reset' | 'card' | 'ledger' | 'loan'

function PictogramIcon({ name }: { name: Pictogram }) {
  const paths: Record<Pictogram, ReactNode> = {
    open: <><rect x="3" y="6" width="18" height="13" rx="2" /><path d="M3 10h18" /><circle cx="18.5" cy="18.5" r="4" fill="#f8f3ed" /><path d="M18.5 16.5v4M16.5 18.5h4" /></>,
    account: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M6 10h12M7 15h6" /></>,
    reset: <><rect x="6" y="10" width="12" height="11" rx="2" /><path d="M9 10V7a3 3 0 0 1 6 0v3M20 12a5 5 0 0 1 1 7M21 15v-3h-3" /></>,
    card: <><rect x="2.5" y="5.5" width="19" height="13" rx="2" /><path d="M2.5 10h19M16 15h2" /></>,
    ledger: <><rect x="5" y="3" width="15" height="18" rx="2" /><path d="M8 3v18M11 16l2-3 2 1 2-5" /></>,
    loan: <><path d="M6 8c0-2 2-2 3-1 1-2 3-2 4 0 2-1 4 0 4 2l-2 3c3 2 5 5 5 7 0 2-3 3-8 3S4 21 4 19c0-2 2-5 5-7L6 8zM9 12h6M9 17h6M12 14v6" /></>,
  }

  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

const shortcuts: { to: string; icon: Pictogram; label: ReactNode }[] = [
  { to: '/accounts/open', icon: 'open', label: '계좌개설' },
  { to: '/accounts', icon: 'account', label: '계좌조회' },
  { to: '/auth/reset', icon: 'reset', label: <>로그인<br />비밀번호 재설정</> },
]

const services: { to: string; icon: Pictogram; title: string; detail: string }[] = [
  { to: '/accounts', icon: 'account', title: '계좌', detail: '내 계좌조회 · 관리' },
  { to: '/cards', icon: 'card', title: '카드', detail: '이용내역 · 결제관리' },
  { to: '/ledger', icon: 'ledger', title: '가계부', detail: '수입 · 지출 관리' },
  { to: '/loans', icon: 'loan', title: '대출', detail: '한도조회 · 신청' },
]

export default function Home() {
  const [searchMessage, setSearchMessage] = useState('')

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSearchMessage('지점 검색은 준비 중입니다.')
  }

  return (
    <div className="branch-home">
      <section className="branch-hero" aria-labelledby="branch-title">
        <img className="branch-hero-art" src="/images/aim-portal.png" alt="" />
        <div className="branch-hero-content">
          <p className="branch-eyebrow">내 손안에 AIM지점 <span aria-hidden="true" /></p>
          <h2 id="branch-title">AIM WON<br /><em>브랜치</em></h2>
          <div className="branch-badges"><span># NO앱설치</span><span># NO인증서</span></div>
          <p className="branch-description">앱 설치도, 복잡한 인증서도 없이<br />지금 바로, AIM의 금융서비스를 만나보세요.</p>
        </div>
      </section>

      <div className="branch-content">
        <AuthStrip />
        <form className="branch-search" onSubmit={onSearch} role="search">
          <input type="search" aria-label="AIM지점 검색" placeholder="AIM지점 방문해 볼까요?" onChange={() => setSearchMessage('')} />
          <button type="submit" aria-label="검색"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><circle cx="10.7" cy="10.7" r="7" /><path d="m16 16 5 5" /></svg></button>
        </form>
        {searchMessage && <p className="branch-search-message" role="status">{searchMessage}</p>}

        <nav className="branch-shortcuts" aria-label="빠른 메뉴">
          {shortcuts.map((item, index) => <Link to={item.to} key={item.to} className={index === 0 ? 'is-primary' : ''}>
            <PictogramIcon name={item.icon} /><strong>{item.label}</strong><span className="branch-shortcut-arrow" aria-hidden="true">→</span>
          </Link>)}
        </nav>

        <section className="branch-services" aria-labelledby="services-title">
          <div className="branch-section-heading"><h3 id="services-title">내 금융</h3><span className="branch-section-rule" aria-hidden="true" /><p>자주 쓰는 금융서비스를 한곳에</p></div>
          <nav className="branch-service-grid" aria-label="금융 서비스">
            {services.map((item) => <Link to={item.to} key={item.to} className="branch-service-card">
              <PictogramIcon name={item.icon} />
              <span className="branch-service-copy"><strong>{item.title}</strong><small>{item.detail}</small></span>
              <span className="branch-service-arrow" aria-hidden="true">→</span>
            </Link>)}
          </nav>
        </section>
      </div>
    </div>
  )
}
