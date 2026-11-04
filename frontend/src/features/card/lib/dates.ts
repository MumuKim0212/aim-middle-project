// 날짜 계산은 모두 KST 기준 'YYYY-MM-DD' 문자열로 한다.
const KST_OFFSET_MS = 9 * 3600 * 1000
const pad = (n: number) => String(n).padStart(2, '0')

export const kstDate = (ms: number) => new Date(ms + KST_OFFSET_MS).toISOString().slice(0, 10)
export const kstTime = (ms: number) => new Date(ms + KST_OFFSET_MS).toISOString().slice(11, 16)

export const dateOf = (y: number, m: number, d: number) =>
  new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10)

export const parseDate = (s: string): [number, number, number] => {
  const [y, m, d] = s.split('-').map(Number)
  return [y, m, d]
}

export const isValidDate = (s: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false
  const [y, m, d] = parseDate(s)
  return dateOf(y, m, d) === s
}

/** 같은 일자로 n개월 이동. 그 일자가 없으면 그 달의 마지막 날 */
export const addMonths = (s: string, n: number) => {
  const [y, m, d] = parseDate(s)
  const first = new Date(Date.UTC(y, m - 1 + n, 1))
  const lastDay = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate()
  return dateOf(first.getUTCFullYear(), first.getUTCMonth() + 1, Math.min(d, lastDay))
}

export const monthStart = (s: string) => `${s.slice(0, 7)}-01`

export const daysBetween = (from: string, to: string) =>
  Math.round((Date.parse(to) - Date.parse(from)) / 86400000)

export const yearsBetween = (birth: string, today: string) => {
  const [by, bm, bd] = parseDate(birth)
  const [ty, tm, td] = parseDate(today)
  return ty - by - (tm < bm || (tm === bm && td < bd) ? 1 : 0)
}

export { pad }
