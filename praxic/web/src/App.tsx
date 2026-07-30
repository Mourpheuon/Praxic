import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { useSSE } from './hooks/useSSE'
import type { ActivityEvent, AuthorizationRequest, PhaseId, RunStatus, SSEDoneEvent } from './types'
import { PHASES, PHASE_LABELS } from './types'

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

  const reset = useCallback(() => {
    setActivities([])
    setSelectedId('')
    setResult(null)
    setElapsed(0)
    setAuthorizations({})
    setAuthorizationBusy('')
    setAuthorizationError('')
  }, [])

  const handleEvent = useCallback((event: ActivityEvent) => {
    setActivities(previous => [...previous, event].slice(-300))
    setSelectedId(event.id)
    const authorization = authorizationFrom(event)
    if (authorization) {
      setAuthorizations(previous => ({ ...previous, [authorization.request_id]: authorization }))
    }
  }, [])

  const handleDone = useCallback((data: SSEDoneEvent) => {
    setResult(data)
    setStartedAt(null)
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

  const activePhase = selected?.phase && PHASE_LABELS[selected.phase]
    ? selected.phase
    : [...activities].reverse().find(activity => PHASE_LABELS[activity.phase])?.phase || ''

  const phaseStatus = (phase: string) => {
    if (phase === activePhase && status === 'running') return 'active'
    if (activities.some(activity => activity.phase === phase)) return 'done'
    return 'idle'
  }

  const selectPhase = (phase: string) => {
    const event = [...activities].reverse().find(activity => activity.phase === phase)
    if (event) setSelectedId(event.id)
  }

  const run = () => {
    const trimmed = question.trim()
    if (!trimmed || status === 'running') return
    reset()
    const nextId = newConversationId()
    setConversationId(nextId)
    setStartedAt(Date.now())
    start(trimmed, context, mode, nextId, [], projectId)
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    run()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault()
      run()
    }
  }

  const stopRun = () => {
    stop()
    setStartedAt(null)
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
                  <span className="phase-node-copy"><strong>{phase.label}</strong><small>{phaseStatus(phase.id) === 'active' ? '当前接触' : phaseStatus(phase.id) === 'done' ? '已留证' : '等待'}</small></span>
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
              {activities.map((activity, index) => {
                const isSelected = activity.id === selected?.id
                const isTool = activity.event_type === 'tool_call'
                const isAuthorization = activity.event_type?.startsWith('authorization_')
                const toolResult = (activity.data?.record as Record<string, any> | undefined)?.result as Record<string, any> | undefined
                const isFailure = toolResult?.status === 'error' || toolResult?.state_classification === 'verification_failed'
                return (
                  <button key={activity.id} className={`activity-row ${isSelected ? 'activity-row--selected' : ''} ${isAuthorization ? 'activity-row--authorization' : ''} ${isFailure ? 'activity-row--failure' : ''}`} onClick={() => setSelectedId(activity.id)}>
                    <span className={`activity-index ${isTool || isAuthorization ? 'activity-index--tool' : ''}`}>{(index + 1).toString().padStart(2, '0')}</span>
                    <span className="activity-bar" />
                    <span className="activity-copy"><small>{isAuthorization ? 'AUTHORIZATION / ' + String(authorizationFrom(activity)?.tool_name || 'ACTION').toUpperCase() : isTool ? 'ACTION / ' + String((activity.data?.tool || 'TOOL')).toUpperCase() : (PHASE_LABELS[activity.phase] || activity.phase).toUpperCase()}</small><strong>{activity.summary || '状态已更新'}</strong></span>
                    <span className="activity-arrow">↗</span>
                  </button>
                )
              })}
            </div>

            {result && <div className={`result-strip ${result.error ? 'result-strip--error' : ''}`}><span className="result-stamp">{result.error ? '!' : '✓'}</span><div><small>OUTPUT / {result.session_id || 'SESSION'}</small><p>{result.error || result.summary}</p></div></div>}

            <form className="command-panel" onSubmit={handleSubmit}>
              <div className="command-label"><span className="square square--yellow" /> 输入下一项现实问题</div>
              <textarea value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={handleKeyDown} placeholder="描述你希望 Praxic 探测、计算、改变或验证的对象……" rows={3} />
              <div className="command-controls">
                <input value={context} onChange={event => setContext(event.target.value)} placeholder="背景约束（可选）" aria-label="背景约束" />
                <input value={projectId} onChange={event => setProjectId(event.target.value)} placeholder="项目 ID" aria-label="项目 ID" />
                <select value={mode} onChange={event => setMode(event.target.value)} aria-label="运行模式"><option value="standard">标准深度</option><option value="fast">快速探测</option><option value="deep">深度行动</option></select>
                {status === 'running' ? <button type="button" className="action-button action-button--dark" onClick={stopRun}><span>■</span> 停止</button> : <button type="submit" className="action-button action-button--red" disabled={!question.trim()}><span>→</span> 启动</button>}
              </div>
            </form>
          </section>

          <aside className="inspector" aria-label="行动详情">
            <div className="inspector-head"><div><p className="eyebrow">INSPECTOR / EVIDENCE</p><h2>证据面板</h2></div><span className="inspector-mark">+</span></div>
            {!selected && <div className="inspector-empty"><span>00</span><p>选择一条活动</p><small>阶段摘要、工具结果、权限记录和验证证据会在这里展开。</small></div>}
            {selected && <div className="inspector-body">
              <div className="detail-tag">{selectedAuthorization ? '行动授权' : selected.event_type === 'tool_call' ? '工具行动' : PHASE_LABELS[selected.phase] || selected.phase}</div>
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
              {!selectedAuthorization && selected.event_type !== 'tool_call' && selected.data && <DetailBlock title="结构化阶段数据" value={jsonText(selected.data)} />}
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
