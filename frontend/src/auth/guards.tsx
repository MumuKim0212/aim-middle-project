import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { safeNext } from '../lib/http'
import { useAuth } from './AuthContext'

const Loading = () => <div className="state">불러오는 중…</div>

/** 로그인이 필요한 화면. 미인증이면 로그인으로(원래 가려던 곳을 next 로), 간편비밀번호가 없으면 설정 화면으로 보낸다(R2·R10). */
export function RequireAuth({ allowSetup = false }: { allowSetup?: boolean }) {
  const { state } = useAuth()
  const loc = useLocation()
  if (state.loading) return <Loading />
  if (!state.authenticated) {
    const next = encodeURIComponent(loc.pathname + loc.search)
    return <Navigate to={`/login?next=${next}${state.expired ? '&expired=1' : ''}`} replace />
  }
  if (state.pinSetupRequired && !allowSetup) return <Navigate to="/auth/pin/setup" replace />
  return <Outlet />
}

/** 로그인·가입 화면. 이미 로그인한 상태면 홈(또는 next)으로 보낸다(7.2). */
export function PublicOnly() {
  const { state } = useAuth()
  const [params] = useSearchParams()
  if (state.loading) return <Loading />
  if (state.authenticated) {
    const next = safeNext(params.get('next'))
    if (state.pinSetupRequired) return <Navigate to={next ? `/auth/pin/setup?next=${encodeURIComponent(next)}` : '/auth/pin/setup'} replace />
    return <Navigate to={next ?? '/'} replace />
  }
  return <Outlet />
}
