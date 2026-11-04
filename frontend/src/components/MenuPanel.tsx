import { useState } from 'react'
import { Link } from 'react-router-dom'

// Sub-items are placeholders: every item links to its feature page until detail pages exist.
const menu = [
  { label: '계좌', to: '/account', items: [] },
  {
    label: '카드',
    to: '/card',
    items: [
      '내 카드 목록·상세',
      '이용내역 조회',
      '청구·결제 예정 금액',
      '카드 분실·정지·재개',
      '한도 조회·변경',
    ],
  },
]

export default function MenuPanel({ onClose }: { onClose: () => void }) {
  const [active, setActive] = useState(menu[0])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="전체 메뉴"
      className="fixed inset-y-0 left-1/2 z-50 flex w-full max-w-[440px] -translate-x-1/2 flex-col bg-white"
    >
      <div className="flex items-start justify-between border-b border-gray-300 px-7 pb-6 pt-8">
        <div>
          <p className="flex items-center gap-2 text-lg text-gray-900">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M7 12h9m-3-3 3 3-3 3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            로그인
          </p>
          <p className="mt-2 text-sm text-gray-500">더 편리해진 금융생활을 만나보세요.</p>
        </div>
        <button type="button" aria-label="메뉴 닫기" onClick={onClose} className="p-1 text-gray-900">
          <svg width="24" height="24" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 3l18 18M21 3 3 21" />
          </svg>
        </button>
      </div>

      <div className="flex flex-1">
        <ul className="w-[104px] shrink-0 bg-gray-100 py-3 pl-2">
          {menu.map((m) => (
            <li key={m.label}>
              <button
                type="button"
                aria-current={m === active}
                onClick={() => setActive(m)}
                className={`h-12 w-full pl-3 text-left text-sm ${
                  m === active ? 'bg-sky-500 font-semibold text-white' : 'text-gray-600'
                }`}
              >
                {m.label}
              </button>
            </li>
          ))}
        </ul>
        <ul className="flex-1 pl-5">
          {active.items.map((item) => (
            <li key={item} className="border-b border-gray-200 last:border-b-0">
              <Link to={active.to} onClick={onClose} className="block py-4 text-sm font-bold text-gray-900">
                {item}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
