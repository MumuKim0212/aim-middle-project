import { useState } from 'react'
import { Link } from 'react-router-dom'
import MenuPanel from './MenuPanel'

export default function Header() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="flex items-center justify-between px-4 py-5">
      <Link to="/" className="flex items-center gap-1.5 text-xl font-bold text-brand">
        {/* Placeholder mark; swap for the official logo asset. */}
        <span className="h-4 w-5 rounded-t-full bg-brand" aria-hidden />
        AIM Bank
      </Link>
      <button
        type="button"
        aria-label="메뉴"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen(true)}
        className="flex flex-col gap-1.5 p-1"
      >
        <span className="h-0.5 w-5 bg-gray-800" />
        <span className="h-0.5 w-5 bg-gray-800" />
        <span className="h-0.5 w-5 bg-gray-800" />
      </button>
      {menuOpen && <MenuPanel onClose={() => setMenuOpen(false)} />}
    </header>
  )
}
