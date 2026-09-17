/** 通知中心：审批请求 / 审批结果 / 事件诊断结果（阻断发票无头诊断推送）。 */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, listNotifications, markNotificationRead } from '../api'
import { useAuth } from '../auth'
import type { NotificationItem } from '../types'

const KIND_LABEL: Record<string, string> = {
  APPROVAL_REQUEST: '审批请求',
  APPROVAL_DECIDED: '审批结果',
  EVENT_DIAG: '事件诊断',
}

const KIND_CLASS: Record<string, string> = {
  APPROVAL_REQUEST: 'pending',
  APPROVAL_DECIDED: 'approved',
  EVENT_DIAG: 'info',
}

export default function Notifications() {
  const { token } = useAuth()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      setItems(await listNotifications(token, unreadOnly))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}：${e.message}` : String(e))
    } finally {
      setLoading(false)
    }
  }, [token, unreadOnly])

  useEffect(() => { void refresh() }, [refresh])

  async function markRead(id: number) {
    if (!token) return
    try {
      await markNotificationRead(token, id)
      setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}：${e.message}` : String(e))
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>通知</h1>
          <p className="desc">审批请求与结果、事件触发的无头诊断结论（ap.invoice.blocked → 自动归因）。</p>
        </div>
        <button className="btn ghost" onClick={() => void refresh()} disabled={loading}>刷新</button>
      </div>

      <div className="filters">
        <button type="button" className={`filter${!unreadOnly ? ' on' : ''}`} onClick={() => setUnreadOnly(false)}>全部</button>
        <button type="button" className={`filter${unreadOnly ? ' on' : ''}`} onClick={() => setUnreadOnly(true)}>未读</button>
      </div>

      {error && <div className="error-banner"><span className="code">ERROR</span>{error}</div>}
      {loading && items.length === 0 && <div className="card empty">加载中……</div>}
      {!loading && items.length === 0 && <div className="card empty">暂无通知。</div>}

      <div className="card">
        {items.map((n) => (
          <div key={n.id} className={`notif-item${n.read ? ' read' : ''}`}>
            <span className="dot" />
            <div>
              <div className="t">
                {n.title}
                <span className={`badge ${KIND_CLASS[n.kind] ?? 'info'}`} style={{ marginLeft: 10 }}>
                  {KIND_LABEL[n.kind] ?? n.kind}
                </span>
                {n.refId && <span className="mono" style={{ marginLeft: 10, fontSize: 12, color: 'var(--muted)' }}>{n.refId}</span>}
              </div>
              {n.body && <div className="b">{n.body}</div>}
            </div>
            <span className="time">{new Date(n.createdAt).toLocaleString('zh-CN')}</span>
            {!n.read && (
              <button type="button" className="btn ghost mark" onClick={() => void markRead(n.id)}>标为已读</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
