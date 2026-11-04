import { kstDate } from './dates'

// 데모 시계. 설정한 시각에서 실제 시간처럼 흐른다 (frozen이면 멈춘다).
// 멈춰 있으면 암호 잠금 카운트다운이 끝나도 목업 서버의 잠금이 풀리지 않기 때문이다.
const BASE = '2026-11-04T09:43:00+09:00'
let base = Date.parse(BASE)
let startedAt = performance.now()
let frozen = false

export const nowMs = () => (frozen ? base : base + (performance.now() - startedAt))

export const setNow = (iso: string, opts?: { frozen?: boolean }) => {
  base = Date.parse(iso)
  startedAt = performance.now()
  frozen = !!opts?.frozen
}

export const advance = (seconds: number) => {
  const current = nowMs()
  base = current + seconds * 1000
  startedAt = performance.now()
}

export const resetClock = () => setNow(BASE)
export const today = () => kstDate(nowMs())
export const nowIso = () => new Date(nowMs()).toISOString()
