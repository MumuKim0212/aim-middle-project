import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiFetch, callJson } from '../lib/http'

export type AuthUser = { id: number; loginId: string; name: string }
export type AuthState = { loading: boolean; authenticated: boolean; pinSetupRequired: boolean; expired: boolean; user: AuthUser | null }

type Ctx = {
  state: AuthState
  /** 서버에 로그인 상태를 다시 묻는다(로그인·가입·간편비밀번호 설정 직후에 부른다) */
  refresh: () => Promise<AuthState>
  logout: () => Promise<void>
}

const initial: AuthState = { loading: true, authenticated: false, pinSetupRequired: false, expired: false, user: null }
const AuthCtx = createContext<Ctx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(initial)

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch('/api/auth/session')
      const d = await res.json()
      const next: AuthState = {
        loading: false, authenticated: !!d.authenticated, pinSetupRequired: !!d.pinSetupRequired,
        expired: !!d.expired, user: d.user ?? null,
      }
      setState(next)
      return next
    } catch {
      const next = { ...initial, loading: false }
      setState(next)
      return next
    }
  }, [])

  useEffect(() => {
    void refresh()
    // 다른 탭에서 로그아웃하거나 시간이 지나 만료됐을 수 있으니, 이 탭으로 돌아오면 다시 확인한다
    const onVisible = () => { if (!document.hidden) void refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  const logout = useCallback(async () => {
    await callJson('POST', '/api/auth/logout').catch(() => undefined)
    setState({ ...initial, loading: false })
  }, [])

  const value = useMemo(() => ({ state, refresh, logout }), [state, refresh, logout])
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export function useAuth(): Ctx {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('AuthProvider 안에서만 쓸 수 있어요')
  return ctx
}
