import { useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const MENU_SECTIONS = [
  { id: 'accounts', label: '계좌조회', items: [{ to: '/accounts', label: '내 계좌조회' }, { to: '/accounts/open', label: '계좌개설' }] },
  { id: 'cards', label: '카드', items: [{ to: '/cards', label: '내 카드 목록·상세' }, { to: '/cards/transactions', label: '이용내역 조회' }, { to: '/cards/billing', label: '청구·결제 예정 금액' }, { to: '/cards/security', label: '카드 분실·정지·재개' }, { to: '/cards/limit', label: '한도 조회' }] },
  { id: 'loans', label: '대출', items: [{ to: '/loans', label: '대출조회' }, { to: '/loans', label: '대출상품' }] },
  { id: 'ledger', label: '가계부', items: [{ to: '/ledger', label: '내 가계부' }, { to: '/ledger/chat', label: '가계부에 물어보기' }, { to: '/ledger/history', label: '소비 내역' }] },
  { id: 'auth', label: '로그인·보안', items: [{ to: '/login', label: '로그인' }, { to: '/signup/1', label: '회원가입' }, { to: '/me', label: '내 정보' }] },
] as const

export default function Layout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [selectedMenu, setSelectedMenu] = useState<string>('accounts')
  const pathname = useLocation().pathname
  const nav = useNavigate()
  const { state: auth, logout } = useAuth()
  const isHome = pathname === '/'
  const activeSection = MENU_SECTIONS.find((section) => section.id === selectedMenu) ?? MENU_SECTIONS[0]

  function openMenu() {
    const section = MENU_SECTIONS.find((entry) => pathname.startsWith(`/${entry.id}`))
    setSelectedMenu(section?.id ?? 'accounts')
    setMenuOpen(true)
  }

  return (
    <div className={isHome ? 'phone is-home' : 'phone'}>
      {isHome ? (
        <header className="app-header branch-header">
          <Link to="/" className="branch-logo" aria-label="AIM Bank 홈"><svg viewBox="0 0 40 30" aria-hidden="true"><path d="M2 17C3 7 11 2 20 2s17 5 18 15c-10 5-26 5-36 0Z" fill="#1378dd" /><path d="M3 20c10 4 24 4 34 0-8 8-26 8-34 0Z" fill="#36a5eb" /></svg><span>AIM Bank</span></Link>
          <button className="branch-menu-button" aria-label="메뉴 열기" onClick={openMenu}><span /><span /><span /></button>
        </header>
      ) : (
        <header className="app-header">
          <span aria-hidden="true" />
          <h1><Link to="/" aria-label="AIM Bank 홈">AIM Bank</Link></h1>
          <button className="icon-btn" aria-label="메뉴" onClick={openMenu}><span className="simple-menu-mark" aria-hidden="true" /></button>
        </header>
      )}

      <main className="app-main">
        <Outlet />
      </main>

      {menuOpen && (
        <div className="drawer-backdrop" onClick={() => setMenuOpen(false)}>
          <aside className="drawer" role="dialog" aria-modal="true" aria-label="전체 메뉴" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <div className="drawer-welcome">{auth.authenticated && auth.user
                ? <><Link to="/me" onClick={() => setMenuOpen(false)}>{auth.user.name}님</Link><p><button type="button" className="drawer-logout" onClick={async () => { setMenuOpen(false); await logout(); nav('/', { replace: true, state: { flash: '로그아웃되었습니다.' } }) }}>로그아웃</button></p></>
                : <><Link to="/login" onClick={() => setMenuOpen(false)}><span className="drawer-login-mark" aria-hidden="true">→</span>로그인</Link><p>더 편리해진 금융생활을 만나보세요.</p></>}</div>
              <button className="icon-btn" aria-label="닫기" onClick={() => setMenuOpen(false)}>
                <span className="simple-close-mark" aria-hidden="true" />
              </button>
            </div>
            <div className="drawer-body">
              <nav className="drawer-categories" aria-label="메뉴 카테고리">
                <Link to={auth.authenticated ? '/home' : '/'} className="drawer-home-link" onClick={() => setMenuOpen(false)}>홈</Link>
                {MENU_SECTIONS.map((section) => <button key={section.id} type="button" className={section.id === selectedMenu ? 'active' : ''} aria-current={section.id === selectedMenu ? 'true' : undefined} onClick={() => setSelectedMenu(section.id)}>{section.label}</button>)}
              </nav>
              <nav className="drawer-submenu" aria-label={`${activeSection.label} 세부 메뉴`}>
                {activeSection.items.map((item) => <Link key={item.label} to={item.to} onClick={() => setMenuOpen(false)}>{item.label}<span aria-hidden="true">›</span></Link>)}
              </nav>
            </div>
            <div className="drawer-guide"><strong>처음 방문하셨나요?</strong><p>앱 설치 없이 AIM Bank를 이용해 보세요.</p><Link to="/accounts/open" onClick={() => setMenuOpen(false)}>계좌개설 바로가기 <span aria-hidden="true">→</span></Link></div>
          </aside>
        </div>
      )}
    </div>
  )
}
