/** 2,000,000 → "2,000,000원" */
export const won = (n: number) => `${n.toLocaleString('ko-KR')}원`

/** 은행 앱 스타일 금액: 150,000,000 → "1억 5,000만원", 33,800,000 → "3,380만원" */
export function koreanAmount(n: number): string {
  const eok = Math.floor(n / 100_000_000)
  const man = Math.floor((n % 100_000_000) / 10_000)
  const parts: string[] = []
  if (eok) parts.push(`${eok.toLocaleString('ko-KR')}억`)
  if (man) parts.push(`${man.toLocaleString('ko-KR')}만`)
  return parts.length ? `${parts.join(' ')}원` : won(n)
}

/** 오늘 기준 D-day. 같은 날이면 0 */
export function dDay(iso: string): number {
  const t = new Date()
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate())
  const [y, m, d] = iso.split('-').map(Number)
  return Math.round((new Date(y, m - 1, d).getTime() - today.getTime()) / 86_400_000)
}

/** "2026-11-10" → "11.10" */
export const shortDate = (iso: string) => iso.slice(5).replace('-', '.')
