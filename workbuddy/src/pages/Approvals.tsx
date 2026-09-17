/** 审批台：PENDING 任务三要素（依据 / 影响 / 快照）+ 批准（铸 OT 唤醒）或拒绝。 */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, decideApproval, listApprovals, resumeApproval } from '../api'
import { useAuth } from '../auth'
import type { Approval, ApprovalStatus } from '../types'

const FILTERS: { key: ApprovalStatus | 'ALL'; label: string }[] = [
  { key: 'PENDING', label: '待审批' },
  { key: 'APPROVED', label: '已批准' },
  { key: 'CONSUMED', label: '已执行' },
  { key: 'REJECTED', label: '已拒绝' },
  { key: 'EXPIRED', label: '已过期' },
  { key: 'ALL', label: '全部' },
]

const STATUS_LABEL: Record<ApprovalStatus, string> = {
  PENDING: '待审批', APPROVED: '已批准', CONSUMED: '已执行', REJECTED: '已拒绝', EXPIRED: '已过期',
}

interface Outcome {
  approvalId: string
  action: 'approve' | 'reject'
  approvalResult: string
  answer: string
}

export default function Approvals() {
  const { token } = useAuth()
  const [filter, setFilter] = useState<ApprovalStatus | 'ALL'>('PENDING')
  const [items, setItems] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [comments, setComments] = useState<Record<string, string>>({})
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  const refresh = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      setItems(await listApprovals(token, filter === 'ALL' ? undefined : filter))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}：${e.message}` : String(e))
    } finally {
      setLoading(false)
    }
  }, [token, filter])

  useEffect(() => { void refresh() }, [refresh])

  async function act(a: Approval, action: 'approve' | 'reject') {
    if (!token || busyId) return
    setBusyId(a.approvalId)
    setError(null)
    try {
      const dec = await decideApproval(token, a.approvalId, action, comments[a.approvalId])
      if (action === 'approve' && dec.oneTimeToken) {
        // 携 OT 唤醒挂起会话（幂等键不变，业务幂等由存量侧保证）
        const res = await resumeApproval(token, a.approvalId, dec.oneTimeToken)
        setOutcome({ approvalId: a.approvalId, action, approvalResult: res.approvalResult, answer: res.answer })
      } else {
        setOutcome({
          approvalId: a.approvalId, action, approvalResult: 'rejected',
          answer: `审批人 ${dec.approver} 已拒绝该请求。原始挂起会话就此终止，不会重发。`,
        })
      }
      await refresh()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}：${e.message}` : String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>审批</h1>
          <p className="desc">
            不可逆写操作（irreversible）在网关强制挂起。批准将铸一次性令牌 OT 并唤醒原会话重发；快照为确认人当时所见。
          </p>
        </div>
        <button className="btn ghost" onClick={() => void refresh()} disabled={loading}>刷新</button>
      </div>

      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`filter${filter === f.key ? ' on' : ''}`}
            onClick={() => setFilter(f.key)}
          >{f.label}</button>
        ))}
      </div>

      {error && <div className="error-banner"><span className="code">ERROR</span>{error}</div>}

      {outcome && (
        <div className={`result-banner ${outcome.approvalResult === 'applied' ? 'applied' : 'rejected'}`}>
          <b className="mono">{outcome.approvalId}</b>
          {outcome.approvalResult === 'applied'
            ? ' —— 已批准并携 OT 唤醒落库：'
            : ' —— 已拒绝，挂起会话终止：'}
          <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{outcome.answer}</div>
        </div>
      )}

      {loading && items.length === 0 && <div className="card empty">加载中……</div>}
      {!loading && items.length === 0 && <div className="card empty">该状态下暂无审批任务。</div>}

      {items.map((a) => (
        <ApprovalCard
          key={a.approvalId}
          a={a}
          busy={busyId === a.approvalId}
          comment={comments[a.approvalId] ?? ''}
          onComment={(v) => setComments((c) => ({ ...c, [a.approvalId]: v }))}
          onAct={(action) => void act(a, action)}
        />
      ))}
    </div>
  )
}

function ApprovalCard(
  { a, busy, comment, onComment, onAct }:
  {
    a: Approval
    busy: boolean
    comment: string
    onComment: (v: string) => void
    onAct: (action: 'approve' | 'reject') => void
  },
) {
  const snapshot = isRecord(a.snapshot) ? a.snapshot : null
  return (
    <div className="card">
      <div className="appr-head">
        <span className="tool">{a.tool}</span>
        <span className={`badge ${a.status.toLowerCase()}`}>{STATUS_LABEL[a.status] ?? a.status}</span>
        <span className="aid mono">{a.approvalId}</span>
        <span className="right">
          {a.requestedBy} 发起 · {new Date(a.createdAt).toLocaleString('zh-CN')}
          {a.approver && ` · 审批人 ${a.approver}`}
        </span>
      </div>
      <div className="appr-body">
        <div className="appr-section">
          <div className="h">依据（为什么做）</div>
          <p>{a.rationale ?? '（未提供）'}</p>
        </div>
        <div className="appr-section">
          <div className="h">影响（动了什么）</div>
          <p>{a.impact ?? '（未提供）'}</p>
        </div>
        {snapshot && (
          <div className="appr-section">
            <div className="h">快照（确认人当时所见）</div>
            <table className="kv">
              <tbody>
                {Object.entries(snapshot).map(([k, v]) => (
                  <tr key={k}><th>{k}</th><td>{renderVal(v)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="appr-section">
          <div className="h">执行参数（params_hash 绑定审批）</div>
          <pre className="json">{JSON.stringify(a.params, null, 2)}</pre>
        </div>

        {a.status === 'PENDING' && (
          <div className="decide-bar">
            <input
              type="text"
              placeholder="审批意见（将随审批留痕）"
              value={comment}
              onChange={(e) => onComment(e.target.value)}
            />
            <button className="btn ok" disabled={busy} onClick={() => onAct('approve')}>批准</button>
            <button className="btn danger" disabled={busy} onClick={() => onAct('reject')}>拒绝</button>
          </div>
        )}
      </div>
    </div>
  )
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function renderVal(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
