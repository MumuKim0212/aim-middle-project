import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

const NAV = [
  { to: '/', label: '홈', icon: '🏠', end: true },
  { to: '/accounts', label: '계좌', icon: '💳' },
  { to: '/cards', label: '카드', icon: '🪪' },
  { to: '/loans', label: '대출', icon: '🏦' },
  { to: '/ledger', label: '가계부', icon: '📒' },
]

export default function Layout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const navigate = useNavigate()

  return (
    <div className="phone">
      <header className="app-header">
        <button className="icon-btn" aria-label="홈" onClick={() => navigate('/')}>
          ⌂
        </button>
        <h1>AIM Bank</h1>
        <button className="icon-btn" aria-label="메뉴" onClick={() => setMenuOpen(true)}>
          ☰
        </button>
      </header>

      <main className="app-main">
        <Outlet />
      </main>

      <nav className="bottom-nav" aria-label="하단 메뉴">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? 'active' : '')}>
            <span className="ico">{n.icon}</span>
            {n.label}
          </NavLink>
        ))}
      </nav>

      {menuOpen && (
        <div className="drawer-backdrop" onClick={() => setMenuOpen(false)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <strong>전체 메뉴</strong>
              <button className="icon-btn" aria-label="닫기" onClick={() => setMenuOpen(false)}>
                ✕
              </button>
            </div>
            {NAV.slice(1).map((n) => (
              <NavLink key={n.to} to={n.to} onClick={() => setMenuOpen(false)}>
                {n.icon} {n.label}
              </NavLink>
            ))}
          </aside>
        </div>
      )}
    </div>
  )
}
