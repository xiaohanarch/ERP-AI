import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Layout from './components/Layout'
import Approvals from './pages/Approvals'
import Callback from './pages/Callback'
import Chat from './pages/Chat'
import Login from './pages/Login'
import Notifications from './pages/Notifications'
import Resolution from './pages/Resolution'

function Protected() {
  const { token, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return <div className="page-loading">正在恢复会话……</div>
  }
  // 未登录：携带当前路径（含查询参数）去登录，授权后原路返回（深链直达演示）
  if (!token) {
    const returnTo = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?returnTo=${returnTo}`} replace />
  }
  return <Layout />
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/callback" element={<Callback />} />
        <Route element={<Protected />}>
          <Route path="/chat" element={<Chat />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/resolution" element={<Resolution />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
