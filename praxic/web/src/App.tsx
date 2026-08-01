import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSSE } from './hooks/useSSE'
import type { ActivityEvent, AuthorizationRequest, RunStatus, SSEDoneEvent } from './types'
import { PHASES, PHASE_ICONS, PHASE_LABELS } from './types'

function newConversationId() {
  return Math.random().toString(36).slice(2, 10)
}

function jsonText(value: unknown) {
  if (value === undefined || value === null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function statusLabel(status: RunStatus) {
  return { idle: '待命', running: '运行中', done: '已完成', error: '需注意' }[status]
}

function authorizationFrom(event?: ActivityEvent): AuthorizationRequest | null {
  const candidate = event?.data?.authorization
  if (!candidate || typeof candidate !== 'object' || !('request_id' in candidate)) return null
  return candidate as unknown as AuthorizationRequest
}

type PhaseColor = 'red' | 'blue' | 'yellow'

interface PhaseGroup {
  id: string
  label: string
  subtitle: string
  icon: string
  code: string
  color: PhaseColor
  events: ActivityEvent[]
}

function normalizePhase(event: ActivityEvent, currentPhase = '') {
  if (PHASE_LABELS[event.phase]) return event.phase
  if (event.phase === 'action') return 'practice'
  if (event.phase === 'authorization') return currentPhase || 'practice'
  return event.phase
}

function normalizeActivity(event: ActivityEvent, currentPhase = ''): ActivityEvent {
  return { ...event, phase: normalizePhase(event, currentPhase) }
}

function recordFrom(event: ActivityEvent) {
  return event.data?.record as Record<string, any> | undefined
}

function toolResultFrom(event: ActivityEvent) {
  return recordFrom(event)?.result as Record<string, any> | undefined
}

function toolNameFrom(event: ActivityEvent) {
  return String(event.data?.tool || recordFrom(event)?.tool || 'TOOL')
}

function activityHasFailure(event: ActivityEvent) {
  const result = toolResultFrom(event)
  const authorization = authorizationFrom(event)
  return result?.status === 'error'
    || result?.state_classification === 'verification_failed'
    || result?.state_classification === 'tool_error'
    || authorization?.status === 'denied'
    || event.event_type === 'error'
}

function isToolProgress(event: ActivityEvent) {
  const result = toolResultFrom(event)
  return event.event_type === 'tool_call'
    && (result?.status === 'running' || /进行中|检索中/.test(event.summary || ''))
}

function canMergeToolProgress(previous: ActivityEvent | undefined, next: ActivityEvent) {
  return Boolean(previous)
    && isToolProgress(previous as ActivityEvent)
    && next.event_type === 'tool_call'
    && previous?.phase === next.phase
    && toolNameFrom(previous as ActivityEvent).toLowerCase() === toolNameFrom(next).toLowerCase()
}

function hasMeaningfulEventData(event: ActivityEvent) {
  const data = event.data
  return Boolean(data && Object.keys(data).some(key => key !== 'event_type'))
}

function isPhaseProgressStart(event: ActivityEvent) {
  return event.event_type === 'phase'
    && !hasMeaningfulEventData(event)
    && /^(正在|开始)/.test(event.summary || '')
}

function canMergePhaseProgress(previous: ActivityEvent | undefined, next: ActivityEvent) {
  return Boolean(previous)
    && isPhaseProgressStart(previous as ActivityEvent)
    && next.event_type === 'phase'
    && previous?.phase === next.phase
    && !/^(正在|开始)/.test(next.summary || '')
}

function mergeActivityData(previousData: Record<string, unknown> | undefined, nextData: Record<string, unknown> | undefined) {
  const previous = previousData || {}
  const next = nextData || {}
  const previousRecord = (previous.record && typeof previous.record === 'object' ? previous.record : {}) as Record<string, any>
  const nextRecord = (next.record && typeof next.record === 'object' ? next.record : {}) as Record<string, any>
  const previousResult = (previousRecord.result && typeof previousRecord.result === 'object' ? previousRecord.result : {}) as Record<string, any>
  const nextResult = (nextRecord.result && typeof nextRecord.result === 'object' ? nextRecord.result : {}) as Record<string, any>
  const merged: Record<string, unknown> = {
    ...previous,
    ...next,
  }
  if (previous.record || next.record) merged.record = {
      ...previousRecord,
      ...nextRecord,
      result: { ...previousResult, ...nextResult },
  }
  return merged
}

function appendActivityEvent(previous: ActivityEvent[], next: ActivityEvent) {
  const last = previous[previous.length - 1]
  if (!canMergeToolProgress(last, next) && !canMergePhaseProgress(last, next)) {
    return [...previous, next].slice(-300)
  }
  return [
    ...previous.slice(0, -1),
    {
      ...last,
      summary: next.summary || last.summary,
      data: mergeActivityData(last.data, next.data),
      timestamp: next.timestamp || last.timestamp,
    },
  ]
}

function localActivity(phase: string, eventType: string, summary: string, data?: Record<string, unknown>): ActivityEvent {
  return {
    id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    timestamp: new Date().toISOString(),
    type: 'local',
    event_type: eventType,
    phase,
    summary,
    data,
  }
}

function SetupGate() {
  const [checking, setChecking] = useState(true)
  const [configured, setConfigured] = useState(true)
  const [provider, setProvider] = useState('deepseek')
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com')
  const [model, setModel] = useState('deepseek-v4-pro')
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/v1/setup/status')
      .then(response => response.json())
      .then(data => {
        setConfigured(data.configured !== false)
        if (data.base_url) setBaseUrl(data.base_url)
        if (data.model) setModel(data.model)
        if (data.provider_key) setProvider(data.provider_key)
      })
      .catch(() => setConfigured(true))
      .finally(() => setChecking(false))
  }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      const response = await fetch('/api/v1/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, base_url: baseUrl, model, api_key: apiKey }),
      })
      if (!response.ok) throw new Error((await response.json()).detail || '配置未保存')
      setConfigured(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '配置未保存')
    }
  }

  if (checking || configured) return null
  return (
    <main className="setup-screen">
      <div className="setup-mark">P</div>
      <div className="setup-copy">
        <p className="eyebrow">PRAXIC / INITIALIZE</p>
        <h1>接入行动引擎</h1>
        <p>填写模型连接信息，建立第一条可观察的运行链。</p>
      </div>
      <form className="setup-form" onSubmit={save}>
        <label>供应商
          <select value={provider} onChange={event => setProvider(event.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI 兼容</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>
        {provider !== 'anthropic' && <label>Base URL
          <input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} />
        </label>}
        <label>Model
          <input value={model} onChange={event => setModel(event.target.value)} />
        </label>
        <label>API Key
          <input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} autoComplete="off" />
        </label>
        {error && <p className="form-error">{error}</p>}
        <button className="action-button action-button--red" type="submit"><span>→</span> 建立连接</button>
      </form>
    </main>
  )
}

export default function App() {
  const [conversationId, setConversationId] = useState(newConversationId)
  const [projectId, setProjectId] = useState('')
  const [question, setQuestion] = useState('')
  const [context, setContext] = useState('')
  const [mode, setMode] = useState('standard')
  const [activities, setActivities] = useState<ActivityEvent[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [result, setResult] = useState<SSEDoneEvent | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [authorizations, setAuthorizations] = useState<Record<string, AuthorizationRequest>>({})
  const [authorizationBusy, setAuthorizationBusy] = useState('')
  const [authorizationError, setAuthorizationError] = useState('')
  const [expandedPhases, setExpandedPhases] = useState<Record<string, boolean>>({})
  const [steeringHistory, setSteeringHistory] = useState<string[]>([])
  const [steerTargetId, setSteerTargetId] = useState('')
  const [steeringBusy, setSteeringBusy] = useState(false)
  const [steeringError, setSteeringError] = useState('')
  const lastPhaseRef = useRef('')

  const reset = useCallback(() => {
    setActivities([])
    setSelectedId('')
    setResult(null)
    setElapsed(0)
    setAuthorizations({})
    setAuthorizationBusy('')
    setAuthorizationError('')
    setExpandedPhases({})
    setSteeringHistory([])
    setSteerTargetId('')
    setSteeringBusy(false)
    setSteeringError('')
    lastPhaseRef.current = ''
  }, [])

  const handleEvent = useCallback((event: ActivityEvent) => {
    const normalized = normalizeActivity(event, lastPhaseRef.current)
    if (PHASE_LABELS[normalized.phase]) lastPhaseRef.current = normalized.phase
    setActivities(previous => appendActivityEvent(previous, normalized))
    setSelectedId(normalized.id)
    const authorization = authorizationFrom(normalized)
    if (authorization) {
      setAuthorizations(previous => ({ ...previous, [authorization.request_id]: authorization }))
    }
  }, [])

  const handleDone = useCallback((data: SSEDoneEvent) => {
    setResult(data)
    setStartedAt(null)
    lastPhaseRef.current = 'reflection'
    const event = localActivity('reflection', data.error ? 'error' : 'result', data.error || data.summary, {
      event_type: data.error ? 'error' : 'result',
      result: data,
    })
    setActivities(previous => [...previous, event].slice(-300))
    setSelectedId(event.id)
  }, [])

  const handleTitle = useCallback(() => {}, [])
  const { status, start, stop } = useSSE({ onEvent: handleEvent, onDone: handleDone, onTitle: handleTitle })

  useEffect(() => {
    if (!startedAt || status !== 'running') return
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 250)
    return () => window.clearInterval(timer)
  }, [startedAt, status])

  const selected = useMemo(
    () => activities.find(activity => activity.id === selectedId) || activities[activities.length - 1],
    [activities, selectedId],
  )
  const selectedAuthorizationEvent = authorizationFrom(selected)
  const selectedAuthorization = selectedAuthorizationEvent
    ? authorizations[selectedAuthorizationEvent.request_id] || selectedAuthorizationEvent
    : null
  const pendingAuthorization = Object.values(authorizations).find(item => item.status === 'pending') || null

  const activePhase = [...activities].reverse().find(activity => {
    return PHASE_LABELS[activity.phase] && activity.event_type !== 'user_question' && activity.event_type !== 'steering'
  })?.phase || ''

  const phaseGroups = useMemo<PhaseGroup[]>(() => {
    const grouped = new Map<string, ActivityEvent[]>()
    for (const activity of activities) {
      const events = grouped.get(activity.phase) || []
      events.push(activity)
      grouped.set(activity.phase, events)
    }

    const known = PHASES.map(phase => ({ ...phase, events: grouped.get(phase.id) || [] }))
      .filter(group => group.events.length > 0)
      .map(group => ({ ...group, color: group.color as PhaseColor }))

    const knownIds = new Set<string>(PHASES.map(phase => phase.id))
    const unknown = [...grouped.entries()]
      .filter(([phase]) => !knownIds.has(phase))
      .map(([phase, events]) => ({
        id: phase,
        label: PHASE_LABELS[phase] || phase,
        subtitle: '运行事件',
        icon: PHASE_ICONS[phase] || '•',
        code: '++',
        color: 'blue' as PhaseColor,
        events,
      }))

    return [...known, ...unknown]
  }, [activities])

  const phaseStatus = (phase: string) => {
    const events = activities.filter(activity => activity.phase === phase)
    const hasPendingAuthorization = events.some(activity => authorizationFrom(activity)?.status === 'pending')
    if (hasPendingAuthorization) return 'waiting'
    if (events.some(activityHasFailure)) return 'error'
    if (phase === activePhase && status === 'running') return 'active'
    if (events.length) return 'done'
    return 'idle'
  }

  const selectPhase = (phase: string) => {
    const event = [...activities].reverse().find(activity => activity.phase === phase)
    if (event) {
      setSelectedId(event.id)
      setExpandedPhases(previous => ({ ...previous, [phase]: true }))
    }
  }

  const togglePhase = (phase: string) => {
    const events = activities.filter(activity => activity.phase === phase)
    const autoExpanded = phase === activePhase
      || events.some(activity => authorizationFrom(activity)?.status === 'pending')
      || events.some(activityHasFailure)
    setExpandedPhases(previous => ({ ...previous, [phase]: !(previous[phase] ?? autoExpanded) }))
  }

  const run = () => {
    const trimmed = question.trim()
    if (!trimmed || status === 'running') return
    reset()
    const nextId = newConversationId()
    setConversationId(nextId)
    setStartedAt(Date.now())
    const questionEvent = localActivity('preprocessing', 'user_question', trimmed, {
      event_type: 'user_question',
      content: trimmed,
    })
    setActivities([questionEvent])
    setSelectedId(questionEvent.id)
    lastPhaseRef.current = 'preprocessing'
    setQuestion('')
    start(trimmed, context, mode, nextId, [], projectId)
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (status === 'running') {
      const anchor = activities[activities.length - 1]
      if (question.trim() && anchor) {
        void sendSteering(question, anchor)
        setQuestion('')
      }
      return
    }
    run()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault()
      if (status === 'running') {
        const anchor = activities[activities.length - 1]
        if (question.trim() && anchor) {
          void sendSteering(question, anchor)
          setQuestion('')
        }
      } else {
        run()
      }
    }
  }

  const stopRun = () => {
    stop()
    setStartedAt(null)
  }

  const sendSteering = async (content: string, anchor: ActivityEvent) => {
    const trimmed = content.trim()
    if (!trimmed || status !== 'running' || steeringBusy) return false
    setSteeringBusy(true)
    setSteeringError('')
    try {
      const response = await fetch('/api/v1/agent/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          action: 'steer',
          content: trimmed,
          // 广播给当前运行以及之后的小循环；历史 steering 由控制器持续保留。
          target_phase: '',
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || '插话未送达，运行可能已经结束')

      const steeringEvent = localActivity(anchor.phase, 'steering', trimmed, {
        event_type: 'steering',
        anchor_id: anchor.id,
        previous_count: steeringHistory.length,
        content: trimmed,
      })
      setActivities(previous => [...previous, steeringEvent].slice(-300))
      setSelectedId(steeringEvent.id)
      setSteeringHistory(previous => [...previous, trimmed])
      setSteerTargetId('')
      return true
    } catch (cause) {
      setSteeringError(cause instanceof Error ? cause.message : '插话未送达')
      return false
    } finally {
      setSteeringBusy(false)
    }
  }

  const resolveAuthorization = async (request: AuthorizationRequest, action: 'approve' | 'deny') => {
    setAuthorizationBusy(request.request_id)
    setAuthorizationError('')
    try {
      const response = await fetch(`/api/v1/agent/authorizations/${encodeURIComponent(request.request_id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, project_id: projectId }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || '授权状态未更新')
      const authorization = payload.authorization as AuthorizationRequest
      setAuthorizations(previous => ({ ...previous, [authorization.request_id]: authorization }))
    } catch (cause) {
      setAuthorizationError(cause instanceof Error ? cause.message : '授权状态未更新')
    } finally {
      setAuthorizationBusy('')
    }
  }

  const phaseIsExpanded = (group: PhaseGroup) => {
    const hasPendingAuthorization = group.events.some(activity => authorizationFrom(activity)?.status === 'pending')
    const hasFailure = group.events.some(activityHasFailure)
    return expandedPhases[group.id] ?? (group.id === activePhase || hasPendingAuthorization || hasFailure)
  }

  return (
    <>
      <SetupGate />
      <div className="praxic-app">
        <header className="topbar">
          <div className="brand-lockup">
            <div className="brand-block">P</div>
            <div><strong>PRAXIC</strong><span>REAL-WORLD INTELLIGENCE</span></div>
          </div>
          <div className="topbar-meta"><span className={`status-pip status-pip--${pendingAuthorization ? 'waiting' : status}`} /> {pendingAuthorization ? '等待授权' : statusLabel(status)} <i /> {elapsed.toString().padStart(2, '0')}s</div>
        </header>

        <main className="workbench">
          <aside className="phase-rail" aria-label="智能体阶段">
            <div className="rail-heading"><span>运行结构</span><b>07</b></div>
            <div className="phase-list">
              {PHASES.map(phase => (
                <button key={phase.id} className={`phase-node phase-node--${phaseStatus(phase.id)}`} onClick={() => selectPhase(phase.id)}>
                  <span className={`phase-code phase-code--${phase.color}`}>{phase.code}</span>
                  <span className="phase-node-copy"><strong>{phase.label}</strong><small>{phaseStatus(phase.id) === 'active' ? '当前接触' : phaseStatus(phase.id) === 'waiting' ? '等待授权' : phaseStatus(phase.id) === 'error' ? '需注意' : phaseStatus(phase.id) === 'done' ? '已留证' : '等待'}</small></span>
                  <span className="phase-node-mark" />
                </button>
              ))}
            </div>
            <div className="rail-footer"><span className="square square--red" /><span>状态连续更新</span></div>
          </aside>

          <section className="activity-column">
            <div className="section-head">
              <div><p className="eyebrow">LIVE ACTIVITY / {conversationId}</p><h1>行动现场</h1></div>
              <div className="head-index">{activities.length.toString().padStart(3, '0')}</div>
            </div>
            <div className={`live-banner ${pendingAuthorization ? 'live-banner--waiting' : ''}`}><span className="live-line" /><span>{pendingAuthorization ? `等待授权：${pendingAuthorization.tool_name}` : status === 'running' ? 'Praxic 正在接触问题与世界状态' : result ? '本次行动已形成结果' : '等待新的现实问题'}</span><span className="live-line live-line--short" /></div>

            <div className="activity-feed">
              {activities.length === 0 && <div className="empty-state"><span className="empty-cross">+</span><p>尚无活动记录</p><small>输入一个需要探测、计算或改变的真实问题</small></div>}
              {phaseGroups.map(group => {
                const expanded = phaseIsExpanded(group)
                const groupStatus = phaseStatus(group.id)
                const lastEvent = group.events[group.events.length - 1]
                const actionCount = group.events.filter(activity => activity.event_type === 'tool_call' || activity.event_type?.startsWith('authorization_')).length || group.events.length
                return (
                  <section key={group.id} className={`phase-group phase-group--${groupStatus} ${expanded ? 'phase-group--expanded' : 'phase-group--collapsed'}`}>
                    <button type="button" className="phase-group__head" onClick={() => togglePhase(group.id)} aria-expanded={expanded}>
                      <span className={`phase-group__icon phase-code--${group.color}`}>{group.icon}</span>
                      <span className="phase-group__title"><strong>{group.label}</strong><small>{group.subtitle}</small></span>
                      <span className="phase-group__meta"><b>{actionCount.toString().padStart(2, '0')}</b><small>{groupStatus === 'active' ? '进行中' : groupStatus === 'waiting' ? '等待授权' : groupStatus === 'error' ? '需注意' : '已完成'}</small></span>
                      <span className="phase-group__summary">{lastEvent?.summary || '等待进入'}</span>
                      <span className="phase-group__chevron">{expanded ? '−' : '+'}</span>
                    </button>
                    {expanded && <div className="phase-group__body">
                      {group.events.map((activity, index) => {
                        const isSelected = activity.id === selected?.id
                        const isTool = activity.event_type === 'tool_call'
                        const isAuthorization = Boolean(authorizationFrom(activity))
                        const isSteering = activity.event_type === 'steering'
                        const isQuestion = activity.event_type === 'user_question'
                        const label = isSteering
                          ? 'STEERING'
                          : isQuestion
                            ? 'USER QUESTION'
                            : isAuthorization
                              ? `AUTHORIZATION / ${String(authorizationFrom(activity)?.tool_name || 'ACTION').toUpperCase()}`
                              : isTool
                                ? String(toolNameFrom(activity)).toUpperCase()
                                : (activity.event_type || 'PHASE').replace(/_/g, ' ').toUpperCase()
                        return (
                          <div key={activity.id} className={`event-row-wrap ${isSelected ? 'event-row-wrap--selected' : ''} ${isTool ? 'event-row-wrap--tool' : ''} ${isAuthorization ? 'event-row-wrap--authorization' : ''} ${isSteering ? 'event-row-wrap--steering' : ''} ${activityHasFailure(activity) ? 'event-row-wrap--failure' : ''}`}>
                            <div
                              className="event-row"
                              role="button"
                              tabIndex={0}
                              onClick={() => setSelectedId(activity.id)}
                              onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(activity.id) } }}
                            >
                              <span className="event-index">{(index + 1).toString().padStart(2, '0')}</span>
                              <span className="event-marker" />
                              <span className="event-copy"><small>{label}</small><strong>{activity.summary || '状态已更新'}</strong></span>
                              {status === 'running' && !isSteering && <button type="button" className="event-steer-trigger" onClick={event => { event.stopPropagation(); setSteerTargetId(activity.id); setSteeringError('') }}>插话</button>}
                              <span className="event-arrow">↗</span>
                            </div>
                            {steerTargetId === activity.id && status === 'running' && <SteeringComposer
                              key={activity.id}
                              historyCount={steeringHistory.length}
                              busy={steeringBusy}
                              error={steeringError}
                              onCancel={() => setSteerTargetId('')}
                              onSend={content => sendSteering(content, activity)}
                            />}
                          </div>
                        )
                      })}
                    </div>}
                  </section>
                )
              })}
            </div>

            <form className="command-panel" onSubmit={handleSubmit}>
              <div className="command-label"><span className="square square--yellow" /> {status === 'running' ? '插入当前小循环的 steering' : '输入下一项现实问题'}</div>
              <textarea value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={handleKeyDown} placeholder={status === 'running' ? '补充方向、纠正判断，或提出一个需要继续回答的问题……（Ctrl+Enter 插话）' : '描述你希望 Praxic 探测、计算、改变或验证的对象……'} rows={3} />
              <div className="command-controls">
                <input value={context} onChange={event => setContext(event.target.value)} placeholder="背景约束（可选）" aria-label="背景约束" />
                <input value={projectId} onChange={event => setProjectId(event.target.value)} placeholder="项目 ID" aria-label="项目 ID" />
                <select value={mode} onChange={event => setMode(event.target.value)} aria-label="运行模式"><option value="standard">标准深度</option><option value="fast">快速探测</option><option value="deep">深度行动</option></select>
                {status === 'running' ? <div className="command-actions">
                  <button type="submit" className="action-button action-button--red" disabled={!question.trim() || steeringBusy}><span>↗</span> 插话</button>
                  <button type="button" className="action-button action-button--dark" onClick={stopRun}><span>■</span> 停止</button>
                </div> : <button type="submit" className="action-button action-button--red" disabled={!question.trim()}><span>→</span> 启动</button>}
              </div>
              {steeringError && status === 'running' && <p className="form-error steering-error">{steeringError}</p>}
              {status === 'running' && steeringHistory.length > 0 && <p className="steering-note">此前已注入 {steeringHistory.length} 条 steering，后续小循环会继续携带。</p>}
            </form>
          </section>

          <aside className="inspector" aria-label="行动详情">
            <div className="inspector-head"><div><p className="eyebrow">INSPECTOR / EVIDENCE</p><h2>证据面板</h2></div><span className="inspector-mark">+</span></div>
            {!selected && <div className="inspector-empty"><span>00</span><p>选择一条活动</p><small>阶段摘要、工具结果、权限记录和验证证据会在这里展开。</small></div>}
            {selected && <div className="inspector-body">
              <div className="detail-tag">{selectedAuthorization ? '行动授权' : selected.event_type === 'tool_call' ? '工具行动' : selected.event_type === 'steering' ? '插话记录' : selected.event_type === 'user_question' ? '用户问题' : selected.event_type === 'result' || selected.event_type === 'error' ? '运行结果' : PHASE_LABELS[selected.phase] || selected.phase}</div>
              <h3>{selected.summary || '状态已更新'}</h3>
              <p className="detail-time">{new Date(selected.timestamp).toLocaleTimeString()}</p>
              {selectedAuthorization && <>
                <div className="metric-grid"><div><small>工具</small><strong>{selectedAuthorization.tool_name}</strong></div><div><small>行动类型</small><strong>{selectedAuthorization.action_kind}</strong></div><div><small>授权状态</small><strong>{selectedAuthorization.status}</strong></div><div><small>作用范围</small><strong>{selectedAuthorization.scope || '外部状态'}</strong></div></div>
                <DetailBlock title="授权原因" value={selectedAuthorization.reason || '该行动会改变外部状态'} />
                <DetailBlock title="调用参数" value={jsonText(selectedAuthorization.parameters)} />
                {selectedAuthorization.status === 'pending' && <div className="authorization-actions">
                  <button type="button" className="action-button action-button--red" disabled={authorizationBusy === selectedAuthorization.request_id} onClick={() => resolveAuthorization(selectedAuthorization, 'approve')}><span>✓</span> 批准</button>
                  <button type="button" className="action-button action-button--dark" disabled={authorizationBusy === selectedAuthorization.request_id} onClick={() => resolveAuthorization(selectedAuthorization, 'deny')}><span>×</span> 拒绝</button>
                </div>}
                {authorizationError && <p className="form-error authorization-error">{authorizationError}</p>}
              </>}
              {!selectedAuthorization && selected.event_type === 'tool_call' && (() => {
                const record = selected.data?.record as Record<string, any> | undefined
                const toolResult = record?.result as Record<string, any> | undefined
                return <>
                  <div className="metric-grid"><div><small>工具</small><strong>{String(selected.data?.tool || record?.tool || '未知')}</strong></div><div><small>状态</small><strong>{String(toolResult?.state_classification || toolResult?.status || '未知')}</strong></div><div><small>世界改变</small><strong>{toolResult?.world_changed === true ? '是' : toolResult?.world_changed === false ? '否' : '未判定'}</strong></div><div><small>耗时</small><strong>{toolResult?.duration_ms ? `${toolResult.duration_ms}ms` : '—'}</strong></div></div>
                  {toolResult?.permission && <DetailBlock title="权限决定" value={jsonText(toolResult.permission)} />}
                  {toolResult?.change && <DetailBlock title="变更记录" value={jsonText(toolResult.change)} />}
                  {toolResult?.verification && <DetailBlock title="回读验证" value={jsonText(toolResult.verification)} />}
                  <DetailBlock title="工具输出" value={String(toolResult?.content || toolResult?.error || '无文本输出')} />
                 </>
               })()}
               {!selectedAuthorization && selected.event_type === 'steering' && <>
                 <div className="metric-grid"><div><small>插入位置</small><strong>{PHASE_LABELS[selected.phase] || selected.phase}</strong></div><div><small>此前插话</small><strong>{String(selected.data?.previous_count || 0)} 条</strong></div><div><small>传递方式</small><strong>持续携带</strong></div><div><small>状态</small><strong>已送达</strong></div></div>
                 <DetailBlock title="插话内容" value={String(selected.data?.content || selected.summary)} />
               </>}
               {!selectedAuthorization && selected.event_type === 'user_question' && <DetailBlock title="用户问题" value={String(selected.data?.content || selected.summary)} />}
               {!selectedAuthorization && (selected.event_type === 'result' || selected.event_type === 'error') && <DetailBlock title="最终输出" value={jsonText(selected.data?.result || selected.summary)} />}
               {!selectedAuthorization && selected.event_type !== 'tool_call' && !['steering', 'user_question', 'result', 'error'].includes(selected.event_type || '') && selected.data && <DetailBlock title="结构化阶段数据" value={jsonText(selected.data)} />}
            </div>}
          </aside>
        </main>
      </div>
    </>
  )
}

function DetailBlock({ title, value }: { title: string; value: string }) {
  return <section className="detail-block"><div className="detail-block-head"><span>{title}</span><b>+</b></div><pre>{value}</pre></section>
}

function SteeringComposer({
  historyCount,
  busy,
  error,
  onCancel,
  onSend,
}: {
  historyCount: number
  busy: boolean
  error: string
  onCancel: () => void
  onSend: (content: string) => Promise<boolean>
}) {
  const [content, setContent] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!content.trim() || busy) return
    const sent = await onSend(content)
    if (sent) setContent('')
  }

  return (
    <form className="steering-composer" onSubmit={submit}>
      <div className="steering-composer__head"><span>在此小循环后插话</span><small>{historyCount ? `此前 ${historyCount} 条会继续携带` : '插话会进入后续小循环'}</small></div>
      <textarea value={content} onChange={event => setContent(event.target.value)} autoFocus rows={2} placeholder="补充事实、修正方向，或提出下一步问题……" />
      <div className="steering-composer__actions">
        {error && <span className="steering-composer__error">{error}</span>}
        <button type="button" className="steering-cancel" onClick={onCancel}>取消</button>
        <button type="submit" className="action-button action-button--red" disabled={!content.trim() || busy}>{busy ? '发送中…' : '注入 steering'}</button>
      </div>
    </form>
  )
}
