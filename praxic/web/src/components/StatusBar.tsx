import type { RunStatus } from '../types'

interface StatusBarProps {
  status: RunStatus
  conversationId: string
  devMode: boolean
  onToggleDev: () => void
  elapsed: number
  showTimer: boolean
}

export default function StatusBar({
  status,
  conversationId,
  devMode,
  onToggleDev,
  elapsed,
  showTimer,
}: StatusBarProps) {
  const statusText: Record<RunStatus, string> = {
    idle: '就绪',
    running: showTimer ? `执行中 · ${elapsed}s` : '执行中…',
    done: '完成',
    error: '错误',
  }

  const statusDot: Record<RunStatus, string> = {
    idle: 'bg-clay',
    running: 'bg-seal animate-pulse',
    done: 'bg-olive',
    error: 'bg-red-600',
  }

  return (
    <div className="flex items-center justify-between px-5 py-2 border-t border-linen/40 bg-cream/80">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${statusDot[status]}`} />
        <span className="text-xs text-warmgray">{statusText[status]}</span>
      </div>

      <div className="flex items-center gap-4">
        <span className="text-[10px] text-warmgray/60">
          会话: {conversationId}
        </span>

        <button
          onClick={onToggleDev}
          className={`text-xs px-2 py-0.5 rounded transition-colors ${
            devMode
              ? 'bg-seal-wash text-seal'
              : 'text-warmgray hover:text-seal'
          }`}
        >
          📡 开发者追踪{devMode ? ' ▲' : ' ▼'}
        </button>
      </div>
    </div>
  )
}
