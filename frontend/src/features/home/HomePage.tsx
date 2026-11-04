import PillButton from '../../components/PillButton'

export default function HomePage() {
  return (
    <main className="px-4 pb-10">
      <section className="px-8 pt-8">
        <p className="text-xl text-gray-800">내 손안에 AIM지점</p>
        <h1 className="mt-1 text-4xl text-brand-dark">
          <b>AIM</b> <span className="text-brand">브랜치</span>
        </h1>
        <div className="mt-3 flex gap-2 text-sm text-white">
          <span className="rounded-full bg-brand px-3 py-1"># NO 앱설치</span>
          <span className="rounded-full bg-brand-light px-3 py-1"># NO 인증서</span>
        </div>
      </section>

      <form
        role="search"
        className="mx-auto mt-14 flex max-w-[272px] items-center rounded-xl border border-brand px-4"
        onSubmit={(e) => e.preventDefault()}
      >
        <input
          type="search"
          placeholder="AIM지점 방문해 볼까요?"
          className="h-11 min-w-0 flex-1 bg-transparent text-sm text-brand outline-none placeholder:text-brand"
        />
        <button type="submit" aria-label="검색" className="text-brand">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <circle cx="10.5" cy="10.5" r="7" />
            <path d="m16 16 5 5" strokeLinecap="round" />
          </svg>
        </button>
      </form>

      <nav className="mt-14 flex gap-2">
        <PillButton active>계좌개설</PillButton>
        <PillButton>계좌조회</PillButton>
        <PillButton>
          로그인
          <br />
          비밀번호 재설정
        </PillButton>
      </nav>
    </main>
  )
}
