/** 对话页：场景选择 + SSE 流式应答（meta/token/tool/error/approval_required/done）。 */
import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, chatStream } from '../api'
import { nid, useAuth } from '../auth'
import type { ChatTurn } from '../types'

const SCENES = [
  { id: 'ap.diag', name: '发票诊断', desc: '单票校验归因 / 差异下钻（读）', write: false },
  { id: 'ap.batch', name: '批量筛查', desc: '阻断清单 / 大额风险（读）', write: false },
  { id: 'ap.taxcode', name: '税码补全', desc: '税码建议与变更（写 · 需审批）', write: true },
] as const

const SAMPLES: Record<string, string[]> = {
  'ap.diag': ['INV-A-001 校验失败的原因是什么？', 'INV-A-003 有什么风险提示？'],
  'ap.batch': ['帮我筛查大额风险的阻断发票', '当前应付余额情况如何？'],
  'ap.taxcode': ['把 INV-A-052 的税码补全为 CN-VAT-13'],
}

export default function Chat() {
  const { token } = useAuth()
  const [scene, setScene] = useState<string>('ap.diag')
  const [cid, setCid] = useState<string>(() => `wb-${nid().slice(0, 12)}`)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [fatal, setFatal] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const samples = useMemo(() => SAMPLES[scene] ?? [], [scene])

  const patch = (id: string, fn: (t: ChatTurn) => ChatTurn) =>
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)))

  const scroll = () => requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: 'smooth' }))

  async function send(textRaw: string) {
    const text = textRaw.trim()
    if (!text || busy || !token) return
    setInput('')
    setFatal(null)
    rememberConversation(cid)
    const aId = nid()
    setTurns((prev) => [
      ...prev,
      { id: nid(), role: 'user', text, tools: [], done: true },
      { id: aId, role: 'assistant', text: '', tools: [], error: null, approval: null, done: false },
    ])
    setBusy(true)
    scroll()
    try {
      await chatStream(token, { message: text, scene, conversationId: cid }, {
        onMeta: (ev) => patch(aId, (t) => ({ ...t, agent: ev.agent, traceId: ev.traceId })),
        onToken: (ev) => { patch(aId, (t) => ({ ...t, text: t.text + ev.text })); scroll() },
        onTool: (ev) => patch(aId, (t) => ({
          ...t, tools: [...t.tools, { tool: ev.tool, arguments: ev.arguments, ok: ev.ok, error: ev.error }],
        })),
        onError: (ev) => patch(aId, (t) => ({
          ...t, error: { code: ev.code, message: ev.message, rule: ev.rule, ruleSource: ev.ruleSource },
        })),
        onApproval: (ev) => patch(aId, (t) => ({
          ...t,
          approval: {
            type: 'approval_required', approvalId: ev.approvalId,
            suggestion: ev.suggestion as { [k: string]: unknown } | undefined,
            rationale: ev.rationale, impact: ev.impact,
          },
        })),
      })
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
      patch(aId, (t) => ({ ...t, error: { code: 'WB.NETWORK', message: msg } }))
    } finally {
      patch(aId, (t) => ({ ...t, done: true }))
      setBusy(false)
      scroll()
    }
  }

  const newConversation = () => {
    setTurns([])
    setFatal(null)
    setCid(`wb-${nid().slice(0, 12)}`)
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>对话</h1>
          <p className="desc">请求经 hub 场景图 → 网关逐跳令牌 → 存量 BO API；工具调用与错误码全程可见。</p>
        </div>
        <button className="btn ghost" onClick={newConversation}>新会话</button>
      </div>

      <div className="scene-bar">
        {SCENES.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`scene-opt${scene === s.id ? ' on' : ''}`}
            onClick={() => setScene(s.id)}
          >
            <div className="t">{s.name}{s.write && <span className="tag"> 写</span>}</div>
            <div className="d">{s.desc}</div>
          </button>
        ))}
      </div>

      <div className="chat-meta">
        <span>会话 <span className="mono">{cid}</span></span>
        {busy && <span className="typing">执行中……</span>}
      </div>

      {fatal && <div className="error-banner"><span className="code">FATAL</span>{fatal}</div>}

      <div className="chat-scroll">
        {turns.length === 0 && (
          <div className="card empty">从下方示例开始，或直接输入你的问题。</div>
        )}
        {turns.map((t) => <TurnView key={t.id} turn={t} />)}
        <div ref={bottom} />
      </div>

      <div className="chat-input">
        <textarea
          value={input}
          placeholder="输入问题，Enter 发送（Shift+Enter 换行）"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input) }
          }}
        />
        <button className="btn" disabled={busy || !input.trim()} onClick={() => void send(input)}>发送</button>
      </div>
      <div className="chips">
        {samples.map((s) => (
          <button key={s} type="button" className="chip" onClick={() => void send(s)}>{s}</button>
        ))}
      </div>
    </div>
  )
}

/** 会话 id 留痕：仅在真正发出消息时记录（解析查看器的最近列表）。 */
function rememberConversation(cid: string): void {
  try {
    const raw = sessionStorage.getItem('wb.cids')
    const list: string[] = raw ? JSON.parse(raw) : []
    sessionStorage.setItem('wb.cids', JSON.stringify([cid, ...list.filter((c) => c !== cid)].slice(0, 20)))
  } catch { /* 留痕失败不影响对话 */ }
}

function TurnView({ turn }: { turn: ChatTurn }) {
  return (
    <div className={`card turn ${turn.role}`}>
      <div className="who">{turn.role === 'user' ? '我' : (turn.agent ? `助手 · ${turn.agent}` : '助手')}</div>

      {turn.tools.length > 0 && (
        <div className="tool-chips">
          {turn.tools.map((tc, i) => (
            <span key={i} className={`tool-chip${tc.ok ? '' : ' bad'}`}>
              {tc.tool}{tc.ok ? '' : ` ✕ ${tc.error?.code ?? ''}`}
            </span>
          ))}
        </div>
      )}

      {turn.error && (
        <div className="error-banner">
          <span className="code">{turn.error.code}</span>
          {turn.error.message}
          {turn.error.rule && <div style={{ marginTop: 4, fontSize: 12 }}>命中护栏：{turn.error.rule}（{turn.error.ruleSource ?? ''} 层）——零工具调用，未触及 BO API</div>}
        </div>
      )}

      {turn.approval && <ApprovalInline approval={turn.approval} />}

      {(turn.text || (turn.role === 'assistant' && turn.done && !turn.error && !turn.approval)) && (
        <div className="body">{turn.text || '（无内容返回）'}</div>
      )}
      {turn.role === 'assistant' && !turn.done && !turn.text && <div className="typing">思考中……</div>}

      {turn.traceId && <div className="chat-meta" style={{ margin: '10px 0 0' }}>trace <span className="mono">{turn.traceId}</span></div>}
    </div>
  )
}

/** 挂起审批卡：三要素（打算做什么 / 依据 / 影响）+ 跳转审批台。 */
function ApprovalInline({ approval }: { approval: NonNullable<ChatTurn['approval']> }) {
  const s = approval.suggestion as Record<string, unknown> | undefined
  return (
    <div className="approval-card">
      <div className="ttl">⏸ 写操作已挂起，等待审批（GW.APPROVAL_REQUIRED）</div>
      <div className="row"><b>审批单：</b><span className="mono">{approval.approvalId}</span></div>
      {s && (
        <div className="row"><b>打算做什么：</b>
          {Object.entries(s).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
        </div>
      )}
      {approval.rationale && <div className="row"><b>依据：</b>{approval.rationale}</div>}
      {approval.impact && <div className="row"><b>影响：</b>{approval.impact}</div>}
      <div className="row" style={{ marginTop: 8 }}>
        <Link to="/approvals">前往审批台处理 →</Link>
      </div>
    </div>
  )
}
