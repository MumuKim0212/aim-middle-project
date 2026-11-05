// 질문 문장 해석 (시안의 규칙 기반 분류). 실제 자연어 라우터가 붙기 전까지의 임시 구현.
import { CATEGORIES, type Intent } from './copy'

/** "2만 원" → 20000, "20,000원" → 20000. 금액이 없으면 null */
export function parseAmount(text: string): number | null {
  const man = text.match(/(\d+(?:\.\d+)?)\s*만\s*원?/)
  if (man) return Math.round(Number(man[1]) * 10000)
  const won = text.match(/(\d[\d,]{3,})\s*원?/)
  return won ? Number(won[1].replace(/[^\d]/g, '')) || null : null
}

export function classify(text: string): Intent {
  if (/지지난달/.test(text)) return 'prev2'
  if (/지난달|저번달/.test(text)) return 'last'
  if (/잔액|통장|계좌/.test(text)) return 'balance'
  if (/예산|얼마 남/.test(text) && parseAmount(text) === null) return 'budget'
  return 'purchase'
}

export const findCategory = (text: string): string | undefined => CATEGORIES.find((c) => text.includes(c))
