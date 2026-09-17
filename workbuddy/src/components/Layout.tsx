/** 布局：深夜蓝侧栏（品牌 / 导航 / 用户）+ 内容区。 */
import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { listNotifications } from '../api'
import { useAuth } from '../auth'

export default function Layout() {
  const { token, user, signOut } = useAuth()
  const [unread, setUnread] = useState(0)

  // 未读角标：挂载 + 每 30s 轮询（演示粒度足够）
  useEffect(() => {
    if (!token) return
    let alive = true
    const tick = () => listNotifications(token, true)
      .then((items) => { if (alive) setUnread(items.length) })
      .catch(() => { /* 角标失败不打扰 */ })
    tick()
    const timer = window.setInterval(tick, 30_000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [token])

  const navCls = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined)

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo" />
          <span className="name">WorkBuddy</span>
          <span className="sub">员工助手</span>
        </div>
        <nav className="nav">
          <NavLink to="/chat" className={navCls}><span className="ic">◈</span> 对话</NavLink>
          <NavLink to="/approvals" className={navCls}><span className="ic">✓</span> 审批</NavLink>
          <NavLink to="/notifications" className={navCls}>
            <span className="ic">◔</span> 通知
            {unread > 0 && <span className="count">{unread > 99 ? '99+' : unread}</span>}
          </NavLink>
          <NavLink to="/resolution" className={navCls}><span className="ic">⌘</span> 解析查看器</NavLink>
        </nav>
        <div className="side-foot">
          <div className="who">{user?.displayName || user?.sub || '…'}</div>
          <span className="tenant">{user?.tenantId ?? ''}</span>
          <button onClick={signOut}>退出登录</button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
