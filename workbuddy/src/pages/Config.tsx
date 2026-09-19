/** 租户配置管理（产品化配置界面）：行业 / 大额阈值 / 术语改完即生效。
 *
 * 产品语义：文件层 = 标品出厂默认（对照展示）；DB 层 = 管理端当前配置
 * （保存即生效，语义工具与护栏解析立即读取）；「恢复出厂」回落文件层。
 * 每次变更记 change log（who / when / what）。 */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, configChanges, getTenantConfig, putTenantConfig, resetTenantConfig } from '../api'
import { useAuth } from '../auth'
import type { ConfigChange, TenantConfig } from '../types'

const INDUSTRIES = [
  { value: 'manufacturing', label: '制造业（加载制造业行业包：术语 + 护栏）' },
  { value: 'trade', label: '贸易业' },
  { value: '', label: '未声明（不加载行业包）' },
]

interface TermRow { business: string; semantic: string; note: string }

export default function Config() {
  const { token, user } = useAuth()
  const tenantId = user?.tenantId ?? ''

  const [cfg, setCfg] = useState<TenantConfig | null>(null)
  const [industry, setIndustry] = useState('')
  const [threshold, setThreshold] = useState('')
  const [terms, setTerms] = useState<TermRow[]>([])
  const [changes, setChanges] = useState<ConfigChange[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!token || !tenantId) return
    setLoading(true)
    setError(null)
    try {
      const [c, log] = await Promise.all([
        getTenantConfig(token, tenantId),
        configChanges(token, tenantId).catch(() => [] as ConfigChange[]),
      ])
      setCfg(c)
      setIndustry(c.config?.industry ?? '')
      setThreshold(String(c.config?.parameters?.large_risk_threshold?.value ?? ''))
      setTerms((c.config?.terms ?? []).map((t) => ({
        business: t.business, semantic: t.semantic, note: t.note ?? '',
      })))
      setChanges(log)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [token, tenantId])

  useEffect(() => { void load() }, [load])

  const patchTerm = (i: number, field: keyof TermRow, value: string): void => {
    setTerms((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: value } : t)))
  }
  const removeTerm = (i: number): void => {
    setTerms((prev) => prev.filter((_, idx) => idx !== i))
  }
  const addTerm = (): void => {
    setTerms((prev) => [...prev, { business: '', semantic: '', note: '' }])
  }

  const save = async (): Promise<void> => {
    if (!token) return
    setBusy(true); setMsg(null); setError(null)
    try {
      const value = Number(threshold)
      if (!Number.isFinite(value) || value <= 0) throw new Error('大额风险阈值必须是正数')
      const next = await putTenantConfig(token, tenantId, {
        industry,
        parameters: {
          large_risk_threshold: {
            value, unit: 'CNY',
            source: `租户管理端配置（${user?.displayName || user?.sub} · 即时生效）`,
            description: '大额风险阈值',
          },
        },
        terms: terms.filter((t) => t.business.trim() && t.semantic.trim()),
      })
      setCfg(next)
      setMsg(`已保存并立即生效（版本 v${next.version}，语义工具与护栏解析即刻读取新配置）`)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const reset = async (): Promise<void> => {
    if (!token) return
    if (!window.confirm('恢复出厂默认？当前管理端配置将被清除（回落文件层）。')) return
    setBusy(true); setMsg(null); setError(null)
    try {
      await resetTenantConfig(token, tenantId)
      setMsg('已恢复出厂默认（文件层生效）')
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="page-loading">正在加载租户配置……</div>

  const fileThreshold = cfg?.fileDefault?.parameters?.large_risk_threshold
  const netPayable = cfg?.config?.metrics?.net_payable

  return (
    <>
      <div className="page-head">
        <div>
          <h1>租户配置 · {tenantId}</h1>
          <p className="desc">
            产品化配置：行业 / 大额阈值 / 术语改完即生效（无需重启或改文件）。
            文件层为标品出厂默认；本页保存写入 DB 层，语义工具与护栏解析立即读取。
          </p>
        </div>
        <div>
          <span className={`badge ${cfg?.source === 'db' ? 'approved' : 'pending'}`}>
            {cfg?.source === 'db' ? `管理端配置 · v${cfg.version}` : '出厂默认（文件层）'}
          </span>
        </div>
      </div>

      {msg && <div className="card" style={{ borderColor: 'var(--ok)' }}>{msg}</div>}
      {error && <div className="card" style={{ borderColor: 'var(--danger)' }}>{error}</div>}

      <div className="card">
        <h3>生效配置</h3>
        <table className="kv">
          <tbody>
            <tr>
              <th>行业声明</th>
              <td>
                <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
                  {INDUSTRIES.map((o) => (
                    <option key={o.value || 'none'} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <div style={{ marginTop: 6, fontSize: 12, color: 'var(--muted)' }}>
                  行业包（Partner 层）按此匹配：术语与护栏随行业切换（护栏解析 ≤10s 缓存后生效）。
                </div>
              </td>
            </tr>
            <tr>
              <th>大额风险阈值</th>
              <td>
                <input type="text" value={threshold}
                  onChange={(e) => setThreshold(e.target.value)} style={{ width: 160 }} />
                <span className="mono" style={{ marginLeft: 10, fontSize: 12 }}>
                  出厂默认 {String(fileThreshold?.value ?? '-')}（{fileThreshold?.source ?? '-'}）
                </span>
              </td>
            </tr>
            <tr>
              <th>术语表</th>
              <td>
                {terms.map((t, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                    <input type="text" placeholder="业务术语（如 进货单）" value={t.business}
                      onChange={(e) => patchTerm(i, 'business', e.target.value)} style={{ width: 170 }} />
                    <input type="text" placeholder="语义实体（如 purchase_order）" value={t.semantic}
                      onChange={(e) => patchTerm(i, 'semantic', e.target.value)} style={{ width: 190 }} />
                    <input type="text" placeholder="说明" value={t.note}
                      onChange={(e) => patchTerm(i, 'note', e.target.value)} style={{ flex: 1 }} />
                    <button className="btn ghost" type="button" onClick={() => removeTerm(i)}>删除</button>
                  </div>
                ))}
                <button className="btn ghost" type="button" onClick={addTerm}>+ 新增术语</button>
              </td>
            </tr>
            <tr>
              <th>指标口径</th>
              <td>
                <span className="mono">net_payable = {netPayable?.formula ?? '-'}</span>
                <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--muted)' }}>
                  {netPayable?.note ?? ''}（口径由语义层定义，当前版本管理端只读）</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <button className="btn ok" disabled={busy} onClick={() => void save()}>保存并生效</button>
          <button className="btn danger" disabled={busy} onClick={() => void reset()}>恢复出厂</button>
          <button className="btn ghost" disabled={busy} onClick={() => void load()}>刷新</button>
        </div>
      </div>

      <div className="card">
        <h3>变更记录（谁在什么时候改了什么）</h3>
        {changes.length === 0 && <p style={{ color: 'var(--muted)', margin: 0 }}>暂无变更（出厂默认生效中）</p>}
        {changes.length > 0 && (
          <table className="kv">
            <tbody>
              {changes.map((c) => (
                <tr key={c.id}>
                  <th className="mono">{(c.ts ?? '').slice(0, 19).replace('T', ' ')}</th>
                  <td>
                    <b>{c.actor ?? '-'}</b> · {c.action === 'reset' ? '恢复出厂' : '更新'}
                    {c.version != null && <span className="mono"> → v{c.version}</span>}
                    {c.patch && (
                      <span className="mono" style={{ marginLeft: 8, fontSize: 12 }}>
                        [{Object.keys(c.patch).join(', ')}]
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
