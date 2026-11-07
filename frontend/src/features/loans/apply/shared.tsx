import { createContext, useContext, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { won } from '../../../format'
import { ApiFail } from '../../../lib/http'
import { errCode, errMsg } from '../../accounts/api'
import type { LoanProduct } from '../api'
import { FIELD_LABEL, type AppState, type Stash } from './model'

/** 신청 화면 틀(Flow)이 단계 화면에 넘기는 값. */
export type FlowCtx = {
  id: string
  step: string
  product: LoanProduct
  products: LoanProduct[]
  flow: string[]
  app: AppState | null // payoff·done 단계에서는 신청이 끝나 서버에 없다
  stash: Stash
  patch: (s: Partial<Stash>) => void
  next: (state?: unknown) => void
  goStep: (s: string) => void
  goCurrent: () => void
}
export const Ctx = createContext<FlowCtx | null>(null)
export const useFlow = () => useContext(Ctx)!

/** 서버 호출 한 번을 감싼다: 처리 중 표시와 마지막 오류를 들고 있다. 실패하면 undefined 를 돌려준다. */
export function useRun() {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<unknown>(null)
  /** handled 가 true 를 돌려주면 그 오류는 호출한 쪽이 처리한 것으로 보고 오류 문구를 띄우지 않는다. */
  async function run<T>(fn: () => Promise<T>, handled?: (x: unknown) => boolean): Promise<T | undefined> {
    setBusy(true); setErr(null)
    try { return await fn() } catch (x) { if (!handled?.(x)) setErr(x); return undefined } finally { setBusy(false) }
  }
  return { busy, err, run, setErr }
}

/** 오류를 code 별로 보여 준다. 상태가 어긋났으면(409) 지금 단계로 돌아가는 버튼을 함께 둔다. */
export function ErrBox({ err }: { err: unknown }) {
  const goCurrent = useContext(Ctx)?.goCurrent // 신청 시작 화면에는 틀(Flow)이 없다
  if (!err) return null
  const code = errCode(err)
  const fields = err instanceof ApiFail ? err.body.details?.fields : undefined
  return (
    <div role="alert">
      <p className="auth-err">{code === 'LOAN_STATE_INVALID' ? '지금 단계에서는 할 수 없는 요청이에요.' : errMsg(err)}{fields && ` (${fields.map((f) => FIELD_LABEL[f.field] ?? f.field).join(', ')})`}</p>
      {code === 'LOAN_STATE_INVALID' && goCurrent && <button type="button" className="ac-inline" onClick={goCurrent}>진행 중인 단계로 이동</button>}
      {(code === 'LOAN_NOT_FOUND' || code === 'LOAN_DUPLICATE_REQUEST' || code === 'LOAN_EXECUTION_FAILED') && <Link to="/loans" className="ac-inline">내 대출 보기</Link>}
    </div>
  )
}

export const dot = (d: string) => d.replace(/-/g, '.')
export const pct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`

/** 사유 코드 목록 한 줄씩(코드 + 문구). */
export function Reasons({ codes, text }: { codes: string[]; text: Record<string, string> }) {
  return <ul className="ln-reasons">{codes.map((c) => <li key={c}><code>{c}</code> {text[c] ?? ''}</li>)}</ul>
}

/** 만원 단위 숫자 입력. 값은 숫자만 담은 문자열이고, 아래에 원 단위 금액을 같이 보여 준다. */
export function ManField({ label, value, onChange, hint, error }: { label: string; value: string; onChange: (v: string) => void; hint?: ReactNode; error?: string | null }) {
  return (
    <label className="auth-field">{label} (만원)
      <input inputMode="numeric" value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, '').replace(/^0+(?=\d)/, ''))} aria-invalid={!!error} />
      {value && <span className="ln-hint">{won(Number(value) * 10_000)}</span>}
      {hint && <span className="ln-hint">{hint}</span>}
      {error && <span className="auth-err">{error}</span>}
    </label>
  )
}

/** 원 단위 표시를 만원 입력값으로. */
export const toMan = (n: number) => String(Math.round(n / 10_000))

/** 둘 중 하나 고르기(예/아니오 등). */
export function Seg<T extends string | boolean>({ label, value, onChange, options }: { label: string; value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="auth-field" role="group" aria-label={label}>{label}
      <div className="ln-seg">
        {options.map(([v, t]) => <button key={String(v)} type="button" className={v === value ? 'on' : ''} aria-pressed={v === value} onClick={() => onChange(v)}>{t}</button>)}
      </div>
    </div>
  )
}
