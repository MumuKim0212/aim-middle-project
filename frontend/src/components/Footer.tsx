const links = ['고객센터', '은행소개', 'PC 버전']

export default function Footer() {
  return (
    <footer className="bg-gray-100 px-4 py-6 text-center">
      <div className="flex justify-center gap-2">
        {links.map((label) => (
          <button
            key={label}
            type="button"
            className="h-10 w-24 border border-gray-400 bg-white text-sm font-medium"
          >
            {label}
          </button>
        ))}
      </div>
      <p className="mt-4 text-xs text-gray-500">
        © AIM BANK <span className="mx-1">금융소비자보호(PC)</span>
        <strong className="text-gray-700">개인정보처리방침(PC)</strong>
      </p>
    </footer>
  )
}
