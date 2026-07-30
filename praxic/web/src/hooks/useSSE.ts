import { useRef, useState, useCallback, useEffect } from 'react'
import type { ActivityEvent, RunStatus, SSEDoneEvent } from '../types'

interface UseSSEOptions {
  onEvent: (event: ActivityEvent) => void
  onDone: (data: SSEDoneEvent) => void
  onTitle?: (title: string, conversationId: string) => void
}

interface UseSSEReturn {
  status: RunStatus
  start: (
    question: string,
    context: string,
    mode: string,
    conversationId: string,
    files?: string[],
    projectId?: string,
  ) => void
  stop: () => void
}

export function useSSE({ onEvent, onDone, onTitle }: UseSSEOptions): UseSSEReturn {
  const [status, setStatus] = useState<RunStatus>('idle')
  const esRef = useRef<EventSource | null>(null)
  const conversationRef = useRef('')

  const close = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
  }, [])

  const stop = useCallback(() => {
    const conversationId = conversationRef.current
    if (conversationId) {
      void fetch('/api/v1/agent/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: conversationId, action: 'stop' }),
      }).catch(() => {})
    }
    close()
    setStatus('idle')
  }, [close])

  const start = useCallback((
    question: string,
    context: string,
    mode: string,
    conversationId: string,
    files: string[] = [],
    projectId = '',
  ) => {
    close()
    conversationRef.current = conversationId
    let url = '/api/v1/agent/run/stream'
      + '?question=' + encodeURIComponent(question)
      + '&context=' + encodeURIComponent(context)
      + '&mode=' + encodeURIComponent(mode)
      + '&conversation_id=' + encodeURIComponent(conversationId)
      + '&project_id=' + encodeURIComponent(projectId)
    if (files.length) url += '&files=' + encodeURIComponent(files.join(','))

    const es = new EventSource(url)
    esRef.current = es
    setStatus('running')

    es.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as Record<string, unknown>
        if (data.heartbeat) return
        if (data.type === 'title') {
          onTitle?.(String(data.title || ''), String(data.conversation_id || ''))
          return
        }
        if (data.done) {
          setStatus(data.error ? 'error' : 'done')
          close()
          onDone(data as unknown as SSEDoneEvent)
          return
        }
        if (data.phase) {
          onEvent({
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            timestamp: new Date().toISOString(),
            type: String(data.type || 'phase'),
            event_type: String(data.event_type || 'phase'),
            phase: String(data.phase),
            summary: String(data.summary || ''),
            data: data.data as Record<string, unknown> | undefined,
          })
        }
      } catch {
        // Ignore malformed heartbeats or partial proxy output.
      }
    }

    es.onerror = () => {
      setStatus('error')
      close()
    }
  }, [close, onDone, onEvent, onTitle])

  useEffect(() => () => close(), [close])

  return { status, start, stop }
}
