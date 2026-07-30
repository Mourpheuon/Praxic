import { useState } from 'react'
import type { ProjectSummary, ConversationSummary } from '../types'

interface SidebarProps {
  conversationId: string
  projectId: string
  projects: ProjectSummary[]
  conversations: ConversationSummary[]
  onProjectChange: (projectId: string) => void
  onRefreshProjects: () => void
  onNewConversation: () => void
  onConversationSelect: (conversationId: string) => void
  onSettingsClick: () => void
}

export default function Sidebar({
  conversationId, projectId, projects, conversations,
  onProjectChange, onRefreshProjects, onNewConversation,
  onConversationSelect, onSettingsClick,
}: SidebarProps) {
  const [showProjectMenu, setShowProjectMenu] = useState(false)

  const currentProject = projects.find(p => p.id === projectId)
  const projectName = currentProject?.name || '默认项目'

  const handleNewProject = async () => {
    setShowProjectMenu(false)
    const name = window.prompt('新项目名称：')
    if (!name || !name.trim()) return
    try {
      const res = await fetch('/api/v1/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        window.alert('创建失败：' + (err.detail || res.status))
        return
      }
      const data = await res.json()
      onRefreshProjects()
      onProjectChange(data.project_id)
    } catch (e) {
      window.alert('创建失败：' + e)
    }
  }

  return (
    <aside className="w-64 bg-linen flex flex-col flex-shrink-0">
      {/* Header */}
      <div className="p-5 pb-3 space-y-1">
        <h1 className="text-xl font-bold text-seal font-display">🧭 Praxic</h1>
        <p className="text-sm text-ink/70 font-display">Agent</p>
      </div>

      <div className="mx-5 border-t border-clay/40" />

      {/* Project selector */}
      <div className="p-5 pb-2">
        <label className="text-xs font-semibold text-ink/70 uppercase tracking-wide">
          当前项目
        </label>
        <div className="relative mt-1.5">
          <button
            onClick={() => setShowProjectMenu(v => !v)}
            className="w-full flex items-center justify-between px-3 py-2
                       bg-paper border border-linen/60 rounded-lg text-sm text-ink
                       hover:border-seal/40 transition-colors"
          >
            <span className="truncate">📁 {projectName}</span>
            <span className="text-clay ml-1 flex-shrink-0">▾</span>
          </button>
          {showProjectMenu && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-paper border
                            border-linen rounded-lg shadow-lg z-20 max-h-60 overflow-y-auto">
              {projects.map(p => (
                <button
                  key={p.id || '__default__'}
                  onClick={() => { onProjectChange(p.id); setShowProjectMenu(false) }}
                  className={
                    'w-full text-left px-3 py-2 text-sm hover:bg-dust/60 flex items-center justify-between '
                    + (projectId === p.id ? 'bg-seal-wash text-seal font-medium' : 'text-ink')
                  }
                >
                  <span className="truncate">{p.id ? '📁' : '📂'} {p.name}</span>
                  <span className="text-clay ml-2 flex-shrink-0">{p.conversation_count}</span>
                </button>
              ))}
              <div className="border-t border-linen/40 mt-1 pt-1">
                <button
                  onClick={handleNewProject}
                  className="w-full text-left px-3 py-2 text-sm text-clay
                             hover:text-seal hover:bg-dust/60"
                >
                  ＋ 新建项目
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mx-5 border-t border-clay/40 mt-1" />

      {/* Conversation list */}
      <div className="flex-1 p-5 pt-3 overflow-y-auto scrollbar-thin">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs font-semibold text-ink/70 uppercase tracking-wide">
            历史对话
          </h2>
          <button
            onClick={onNewConversation}
            className="text-xs text-seal hover:text-seal-light transition-colors"
            title="新建对话"
          >
            ＋ 新对话
          </button>
        </div>
        {conversations.length === 0 ? (
          <p className="text-sm text-ink/40 py-2">尚无历史记录</p>
        ) : (
          <div className="space-y-1">
            {conversations.map(conv => (
              <button
                key={conv.id}
                onClick={() => onConversationSelect(conv.id)}
                className={
                  'w-full text-left px-2 py-2 rounded-md transition-colors '
                  + (conv.id === conversationId ? 'bg-seal-wash' : 'hover:bg-dust/60')
                }
              >
                <div className="truncate text-sm text-ink/80 font-medium">
                  {conv.name || conv.id}
                </div>
                <div className="truncate text-xs text-clay mt-0.5">
                  {conv.last_question || (conv.question_count + ' 轮对话')}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mx-5 border-t border-clay/40" />

      {/* Footer */}
      <div className="p-5 space-y-2">
        <button
          onClick={onSettingsClick}
          className="text-xs text-ink/70 hover:text-seal hover:bg-seal-wash px-2 py-1 rounded transition-colors"
        >
          ⚙ 设置
        </button>
        <p className="text-xs text-ink/50">
          会话: {conversationId}
        </p>
      </div>
    </aside>
  )
}
