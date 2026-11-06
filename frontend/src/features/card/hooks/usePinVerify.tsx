import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../api/errors'
import PinVerifyDialog from '../components/PinVerifyDialog'

type Req = { description: string }
type Run<T> = { ok: true; value: T } | { ok: false }

type PinVerify = {
  /** true: 통과(또는 5분 안에 이미 확인함), false: 사용자가 취소 */
  ensureVerified: (req: Req) => Promise<boolean>
  /** 기억해 둔 확인 시각을 지운다 */
  invalidate: () => void
  /** 확인 → fn 실행. 서버가 PIN_VERIFICATION_REQUIRED 로 답하면 확인을 다시 받고 한 번 더 시도한다. ok:false 는 취소 */
  runVerified: <T>(req: Req, fn: () => Promise<T>) => Promise<Run<T>>
}

const Ctx = createContext<PinVerify | null>(null)

/** 서버가 기준이라 기억해 둔 만료 시각은 힌트일 뿐이다. 간편비밀번호 값은 어디에도 두지 않는다. */
export function PinVerifyProvider({ children }: { children: ReactNode }) {
  const validUntil = useRef(0)
  const [open, setOpen] = useState<{ description: string; resolve: (ok: boolean) => void } | null>(null)

  const ensureVerified = useCallback(
    (req: Req) =>
      performance.now() < validUntil.current
        ? Promise.resolve(true)
        : new Promise<boolean>((resolve) => setOpen({ description: req.description, resolve })),
    [],
  )
  const invalidate = useCallback(() => {
    validUntil.current = 0
  }, [])
  const runVerified = useCallback(
    async <T,>(req: Req, fn: () => Promise<T>): Promise<Run<T>> => {
      for (let attempt = 0; ; attempt++) {
        if (!(await ensureVerified(req))) return { ok: false }
        try {
          return { ok: true, value: await fn() }
        } catch (e) {
          if (attempt === 0 && e instanceof ApiError && e.code === 'PIN_VERIFICATION_REQUIRED') {
            invalidate()
            continue
          }
          throw e
        }
      }
    },
    [ensureVerified, invalidate],
  )
  const value = useMemo(() => ({ ensureVerified, invalidate, runVerified }), [ensureVerified, invalidate, runVerified])

  const close = (ok: boolean) => {
    open?.resolve(ok)
    setOpen(null)
  }

  return (
    <Ctx.Provider value={value}>
      {children}
      {open && (
        <PinVerifyDialog
          description={open.description}
          onVerified={(seconds) => {
            validUntil.current = performance.now() + seconds * 1000
            close(true)
          }}
          onCancel={() => close(false)}
        />
      )}
    </Ctx.Provider>
  )
}

export function usePinVerify(): PinVerify {
  const v = useContext(Ctx)
  if (!v) throw new Error('usePinVerify must be used inside PinVerifyProvider')
  return v
}
