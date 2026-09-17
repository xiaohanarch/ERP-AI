/** 解析查看器：三层资产（Standard → Partner → Tenant）在本次会话实际用到了哪层哪版本。 */
import { useState } from 'react'
import { ApiError, listResolutions } from '../api'
import { useAuth } from '../auth'
import type { ResolutionItem } from '../types'

/** Chat 页写入的最近会话 id（解析留痕按 conversation_id 查询）。 */
function recentCids(): string[] {
  try {
    const raw = sessionStorage.getItem('wb.cids')
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

export default function Resolution() {
  const { token } = useAuth()
  const [cid, setCid] = useState('')
  const [items, setItems] = useState<ResolutionItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function query(idRaw: string) {
    const id = idRaw.trim()
    if (!token) return
    setLoading(true)
    setError(null)
    setItems(null)
    try {
      const found = await listResolutions(token, id)
      setItems(found)
      if (found.length === 0) setError('该会话没有解析留痕（未产生回答的会话不留痕，例如护栏拦截或挂起审批）。')
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}：${e.message}` : String(e))
    } finally {
      setLoading(false)
    }
  }

  const recents = recentCids()

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>解析查看器</h1>
          <p className="desc">
            资产解析顺序 Standard → Partner → Tenant（确定性）；仅 overridable 标品资产可被覆盖，
            护栏类叠加只能加严——放松类叠加会被拒绝并留痕。
          </p>
        </div>
      </div>

      <div className="res-query">
        <input
          type="text"
          placeholder="conversation_id，例如 wb-xxxxxxxxxxxx"
          value={cid}
          onChange={(e) => setCid(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void query(cid) }}
        />
        <button className="btn" disabled={loading || !cid.trim()} onClick={() => void query(cid)}>查询</button>
      </div>

      {recents.length > 0 && (
        <div className="res-recent">
          {recents.map((id) => (
            <button key={id} type="button" className="chip mono" onClick={() => { setCid(id); void query(id) }}>
              {id}
            </button>
          ))}
        </div>
      )}

      {error && <div className="error-banner"><span className="code">NOTE</span>{error}</div>}
      {loading && <div className="card empty">查询中……</div>}

      {items?.map((r, i) => {
        const snap = r.resolution
        const rules = snap?.guardrails?.rules ?? []
        const rejected = snap?.guardrails?.rejectedOverlays ?? []
        const assets = snap?.prompt?.assets ?? []
        return (
        <div key={i} className="card">
          <div className="appr-head">
            <span className="tool">{r.scene}</span>
            <span className="badge info">{r.tenantId ?? '无租户'}</span>
            <span className="right">{r.createdAt ? new Date(r.createdAt).toLocaleString('zh-CN') : ''}</span>
          </div>
          <div className="appr-body">
            <div className="appr-section">
              <div className="h">生效护栏（rules）</div>
              {rules.length > 0 ? (
                <table className="kv">
                  <tbody>
                    {rules.map((rule) => (
                      <tr key={rule.id}>
                        <th className="mono">{rule.id}</th>
                        <td>
                          <span className={`badge ${rule.action === 'refuse' ? 'rejected' : 'info'}`}>{rule.action}</span>
                          <span className="layer-pill" style={{ marginLeft: 8 }}>{rule.sourceLayer} 层</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p>（无护栏规则记录）</p>}
            </div>

            {rejected.length > 0 && (
              <div className="appr-section">
                <div className="h">被拒绝的叠加（放松类，仅加严原则）</div>
                <pre className="json">{JSON.stringify(rejected, null, 2)}</pre>
              </div>
            )}

            <div className="appr-section">
              <div className="h">系统提示词资产</div>
              {assets.length > 0 ? (
                <table className="kv">
                  <tbody>
                    {assets.map((asset) => (
                      <tr key={asset.asset}>
                        <th className="mono">{asset.asset}</th>
                        <td>
                          {asset.layers.map((l) => (
                            <span key={l.layer} className={`layer-pill${l.layer === 'tenant' ? ' tenant' : ''}`}>
                              {l.layer} · {l.version ?? '—'}
                            </span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p>（无提示词资产记录）</p>}
            </div>
          </div>
        </div>
        )
      })}
    </div>
  )
}
