/** API 客户端：OAuth 授权码换令牌 + 网关审批/通知 + hub 聊天（SSE）与解析留痕。 */
import type {
  Approval, ConfigChange, DecideResult, NotificationItem, ResolutionItem, ResumeResult,
  TenantConfig, WhoAmI,
} from './types'

const GW = (import.meta.env.VITE_GW_BASE as string | undefined) ?? 'http://localhost:8000'
const HUB = (import.meta.env.VITE_HUB_BASE as string | undefined) ?? 'http://localhost:8081'

/** OAuth 客户端注册（网关 service_clients 表的演示凭据）。 */
export const OAUTH = {
  clientId: 'workbuddy',
  clientSecret: 'workbuddy-demo-secret',
  redirectUri: () => `${window.location.origin}/callback`,
  /** 授权码入口（浏览器整页跳转到网关统一登录）。 */
  authorizeUrl: (state: string) =>
    `${GW}/gw/oauth/authorize?response_type=code&client_id=${encodeURIComponent(OAUTH.clientId)}`
    + `&redirect_uri=${encodeURIComponent(OAUTH.redirectUri())}`
    + (state ? `&state=${encodeURIComponent(state)}` : ''),
}

export class ApiError extends Error {
  code: string
  status: number
  constructor(code: string, message: string, status = 0) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function parseError(resp: Response): Promise<ApiError> {
  let code = `HTTP ${resp.status}`
  let message = resp.statusText || '请求失败'
  try {
    const body = await resp.json()
    const err = body?.error ?? body
    if (err?.code) code = err.code
    if (err?.message) message = err.message
  } catch { /* 保底使用 HTTP 状态 */ }
  return new ApiError(code, message, resp.status)
}

/** 统一 JSON 请求；401 由调用方决定跳转登录。 */
async function req(path: string, token: string, init?: RequestInit): Promise<Response> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  })
  if (!resp.ok) throw await parseError(resp)
  return resp
}

// ---------------------------------------------------------------- OAuth
export async function exchangeCode(code: string): Promise<{ token: string; expiresIn: number }> {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    client_id: OAUTH.clientId,
    client_secret: OAUTH.clientSecret,
  })
  const resp = await fetch(`${GW}/gw/oauth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!resp.ok) throw await parseError(resp)
  const data = await resp.json()
  return { token: data.access_token, expiresIn: data.expires_in ?? 43200 }
}

export async function whoami(token: string): Promise<WhoAmI> {
  return (await req(`${GW}/gw/auth/whoami`, token)).json()
}

// ---------------------------------------------------------------- 审批
export async function listApprovals(token: string, status?: string): Promise<Approval[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  const data = await (await req(`${GW}/gw/approvals${qs}`, token)).json()
  return data.items ?? []
}

export async function decideApproval(
  token: string, approvalId: string, action: 'approve' | 'reject', comment?: string,
): Promise<DecideResult> {
  return (await req(`${GW}/gw/approvals/${encodeURIComponent(approvalId)}/decision`, token, {
    method: 'POST',
    body: JSON.stringify({ action, comment: comment || null }),
  })).json()
}

/** 审批通过后唤醒挂起的会话（携一次性令牌 OT 重发，幂等键不变）。 */
export async function resumeApproval(
  token: string, approvalId: string, oneTimeToken: string,
): Promise<ResumeResult> {
  return (await req(`${HUB}/internal/resume`, token, {
    method: 'POST',
    body: JSON.stringify({ approvalId, oneTimeToken }),
  })).json()
}

// ---------------------------------------------------------------- 通知
export async function listNotifications(token: string, unreadOnly = false): Promise<NotificationItem[]> {
  const data = await (await req(`${GW}/gw/notifications${unreadOnly ? '?unread_only=true' : ''}`, token)).json()
  return data.items ?? []
}

export async function markNotificationRead(token: string, id: number): Promise<void> {
  await req(`${GW}/gw/notifications/${id}/read`, token, { method: 'POST' })
}

// ---------------------------------------------------------------- 解析留痕
export async function listResolutions(token: string, conversationId: string): Promise<ResolutionItem[]> {
  const data = await (await req(
    `${HUB}/internal/resolution?conversation_id=${encodeURIComponent(conversationId)}`, token)).json()
  return data.items ?? []
}

// ---------------------------------------------------------------- 聊天（SSE）
export interface ChatHandlers {
  onMeta?: (ev: { conversationId: string; scene: string; agent: string | null; traceId: string }) => void
  onToken?: (ev: { text: string }) => void
  onTool?: (ev: { tool: string; arguments?: unknown; ok: boolean; error?: { code: string; message: string } | null }) => void
  onError?: (ev: { code: string; message: string; rule?: string; ruleSource?: string }) => void
  onApproval?: (ev: { approvalId: string; suggestion?: unknown; rationale?: string; impact?: string }) => void
}

/** POST /chat/stream，解析 `data: {...}` SSE 事件流直到 done。 */
export async function chatStream(
  token: string, body: { message: string; scene: string; conversationId: string }, h: ChatHandlers,
): Promise<void> {
  const resp = await fetch(`${HUB}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) throw await parseError(resp)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, sep)
      buf = buf.slice(sep + 2)
      for (const line of raw.split('\n')) {
        if (!line.startsWith('data: ')) continue
        dispatch(line.slice(6), h)
      }
    }
  }
}

function dispatch(text: string, h: ChatHandlers): void {
  let ev: { type?: string }
  try {
    ev = JSON.parse(text)
  } catch {
    return
  }
  switch (ev.type) {
    case 'meta': h.onMeta?.(ev as never); break
    case 'token': h.onToken?.(ev as never); break
    case 'tool': h.onTool?.(ev as never); break
    case 'error': h.onError?.(ev as never); break
    case 'approval_required': h.onApproval?.(ev as never); break
    default: break
  }
}

// ---------------------------------------------------------------- 租户配置（管理端）
/** 产品化配置界面：阈值/术语/行业改完即生效（语义层 DB 优先，文件层为出厂默认）。 */
export async function getTenantConfig(token: string, tenantId: string): Promise<TenantConfig> {
  return (await req(`${GW}/gw/tenants/${encodeURIComponent(tenantId)}/config`, token)).json()
}

export async function putTenantConfig(
  token: string, tenantId: string, patch: Record<string, unknown>,
): Promise<TenantConfig> {
  return (await req(`${GW}/gw/tenants/${encodeURIComponent(tenantId)}/config`, token, {
    method: 'PUT',
    body: JSON.stringify({ patch }),
  })).json()
}

export async function resetTenantConfig(token: string, tenantId: string): Promise<TenantConfig> {
  return (await req(`${GW}/gw/tenants/${encodeURIComponent(tenantId)}/config`, token, {
    method: 'DELETE',
  })).json()
}

export async function configChanges(token: string, tenantId: string): Promise<ConfigChange[]> {
  const data = await (await req(
    `${GW}/gw/tenants/${encodeURIComponent(tenantId)}/config/changes`, token)).json()
  return data.changes ?? []
}
