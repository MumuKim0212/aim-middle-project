import { kstDate, kstTime } from './dates'

export const formatWon = (n: number) => `${n.toLocaleString('ko-KR')}원`
export const formatDate = (s: string) => s.replace(/-/g, '.')
export const formatDateTime = (iso: string) => {
  const ms = Date.parse(iso)
  return `${formatDate(kstDate(ms))} ${kstTime(ms)}`
}
export const formatRate = (rate: number) => `${rate.toFixed(1)}%`
