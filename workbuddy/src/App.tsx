import { Navigate, Route, Routes } from 'react-router-dom'
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
  if (loading) {
    return <div className="page-loading">正在恢复会话……</div>
  }
  return token ? <Layout /> : <Navigate to="/login" replace />
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
