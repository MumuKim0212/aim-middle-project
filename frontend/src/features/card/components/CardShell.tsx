import { Outlet } from 'react-router-dom'
import '../card.css'

// shortcut: no RequireAuth guard here yet (main has no auth; backend uses a fixed demo member).
export default function CardShell() {
  return (
    <div className="card-feature">
      <Outlet />
    </div>
  )
}
