/** 类型定义：网关 / hub 契约（与 erp-ai-action、erp-ai-hub 对应）。 */

export interface WhoAmI {
  sub: string
  tenantId: string
  azp: string
  displayName?: string
  scope: string[]
  configAdmin?: boolean
}

/** 租户叠加（与 erp-ai-context overlays 同构：industry / parameters / terms / metrics）。 */
export interface TenantOverlay {
  tenant_id?: string
  industry?: string
  parameters?: Record<string, { value: unknown; source?: string; description?: string }>
  terms?: { business: string; semantic: string; note?: string }[]
  metrics?: Record<string, { formula?: string; includes_accrual?: boolean; note?: string }>
}

/** 租户配置（管理端）：source=db 为管理端当前配置，file 为出厂默认。 */
export interface TenantConfig {
  tenantId: string
  source: 'db' | 'file'
  version: number | null
  updatedBy: string | null
  updatedAt: string | null
  config: TenantOverlay | null
  fileDefault: TenantOverlay | null
}

export interface ConfigChange {
  id: number
  actor: string | null
  action: string
  patch: Record<string, unknown> | null
  version: number | null
  ts: string | null
}

export interface ToolEvent {
  tool: string
  arguments?: unknown
  ok: boolean
  error?: { code: string; message: string } | null
}

export interface ErrorEvent {
  code: string
  message: string
  rule?: string
  ruleSource?: string
}

export interface ApprovalPayload {
  type: 'approval_required'
  approvalId: string
  suggestion?: { [k: string]: unknown }
  rationale?: string
  impact?: string
}

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  text: string
  tools: ToolEvent[]
  error?: ErrorEvent | null
  approval?: ApprovalPayload | null
  agent?: string | null
  traceId?: string | null
  done: boolean
}

export type ApprovalStatus =
  | 'PENDING' | 'APPROVED' | 'CONSUMED' | 'REJECTED' | 'EXPIRED'

export interface Approval {
  approvalId: string
  tenantId: string
  scene: string | null
  agentId: string | null
  tool: string
  params: unknown
  paramsHash: string
  requestedBy: string
  status: ApprovalStatus
  approver: string | null
  decidedAt: string | null
  rationale: string | null
  impact: string | null
  snapshot: unknown
  createdAt: string
  expiresAt: string
}

export interface DecideResult {
  approvalId: string
  status: ApprovalStatus
  approver: string
  oneTimeToken?: string
  expiresIn?: number
}

export interface ResumeResult {
  ok: boolean
  approvalId: string
  approvalResult: string
  conversationId: string | null
  answer: string
}

export interface NotificationItem {
  id: number
  kind: 'APPROVAL_REQUEST' | 'APPROVAL_DECIDED' | 'EVENT_DIAG' | string
  title: string
  body: string | null
  refId: string | null
  read: boolean
  createdAt: string
}

export interface ResolutionSnapshot {
  scene?: string
  tenantId?: string | null
  guardrails?: {
    rules: { id: string; action: string; sourceLayer: string }[]
    rejectedOverlays: { [k: string]: unknown }[]
  }
  prompt?: { resolved: boolean; assets: { asset: string; layers: { layer: string; version?: string }[] }[] }
}

export interface ResolutionItem {
  conversationId: string
  scene: string
  tenantId: string | null
  resolution: ResolutionSnapshot | null
  createdAt: string
}
