import { Outlet } from 'react-router-dom'
import '../card.css'
import { PinVerifyProvider } from '../hooks/usePinVerify'

// 로그인 보호는 App.tsx 의 RequireAuth 가 맡는다.
export default function CardShell() {
  return (
    <div className="card-feature">
      <PinVerifyProvider>
        <Outlet />
      </PinVerifyProvider>
    </div>
  )
}
