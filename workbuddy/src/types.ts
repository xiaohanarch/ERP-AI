/** 类型定义：网关 / hub 契约（与 erp-ai-action、erp-ai-hub 对应）。 */

export interface WhoAmI {
  sub: string
  tenantId: string
  azp: string
  displayName?: string
  scope: string[]
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
