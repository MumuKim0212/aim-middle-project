// GET /api/home 응답 타입 (backend/app/main.py 와 맞춘다)
export type LoanProduct = {
  id: string
  type: 'general' | 'gov' | 'org' | 'refi'
  name: string
  maxAmount: number | null
  term: string | null
  tags: string[]
  icon: string | null
}

export type MyLoan = {
  contractNo: string
  productName: string
  balance: number
  amount: number
  rate: number
  nextDueDate: string | null
  nextDueAmount: number
}

export type HomeData = {
  member: { id: string; name: string }
  accounts: {
    totalBalance: number
    items: { id: string; bankName: string; masked: string; balance: number; primary: boolean }[]
  }
  cards: {
    count: number
    monthSpent: number
    items: { id: string; name: string; type: 'credit' | 'debit'; last4: string; status: string }[]
  }
  ledger: { month: string; budget: number; spent: number; remaining: number; usageRate: number }
  loans: {
    count: number
    totalBalance: number
    nextDueDate: string | null
    nextDueAmount: number
    items: MyLoan[]
    products: LoanProduct[]
  }
}

export async function fetchHome(): Promise<HomeData> {
  const res = await fetch('/api/home')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
