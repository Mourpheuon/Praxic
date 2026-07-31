export const PHASES = [
  { id: 'preprocessing', label: '问题解析', subtitle: '边界与意图', icon: '◇', code: '00', color: 'red' },
  { id: 'investigation', label: '调查研究', subtitle: '事实与证据', icon: '□', code: '01', color: 'blue' },
  { id: 'contradiction', label: '矛盾分析', subtitle: '张力与驱动', icon: '×', code: '02', color: 'yellow' },
  { id: 'rational', label: '理性认识', subtitle: '关系与规律', icon: '△', code: '03', color: 'blue' },
  { id: 'practice', label: '实践检验', subtitle: '行动与验证', icon: '＋', code: '04', color: 'yellow' },
  { id: 'reflection', label: '反思', subtitle: '验证与修正', icon: '↻', code: '05', color: 'blue' },
] as const

export type PhaseId = typeof PHASES[number]['id']
export type RunStatus = 'idle' | 'running' | 'done' | 'error'

export const PHASE_LABELS: Record<string, string> = Object.fromEntries(
  PHASES.map(phase => [phase.id, phase.label]),
)
export const PHASE_ICONS: Record<string, string> = Object.fromEntries(
  PHASES.map(phase => [phase.id, phase.icon]),
)

export interface ActivityEvent {
  type?: string
  event_type?: string
  phase: string
  summary: string
  data?: Record<string, unknown>
  timestamp: string
  id: string
}

export interface AuthorizationRequest {
  request_id: string
  tool_name: string
  action_kind: string
  parameters: Record<string, unknown>
  scope: string
  reason: string
  status: 'pending' | 'approved' | 'denied' | 'expired'
  grant_id?: string
  created_at: string
  resolved_at?: string
}

export interface TraceRecord {
  phase: string
  tag: string
  output: string
  seq: number
}

export interface SSEDoneEvent {
  done: true
  summary: string
  action_items: string[]
  session_id: string
  conversation_id?: string
  generated_files?: Array<{ path: string; description: string; size_bytes: number }>
  error?: string
}

export interface ProjectSummary {
  id: string
  name: string
  workspace_dir: string
  data_dir?: string
  conversation_count: number
  last_active: string
}

export interface ConversationSummary {
  id: string
  name: string
  question_count: number
  last_question: string
  last_active: string
}

export interface ConversationTurn {
  session_id: string
  question: string
  summary: string
  action_items: string[]
  created_at: string
}
