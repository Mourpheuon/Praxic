import { useEffect, useState } from 'react'

interface SettingsDialogProps {
  permissionMode: string
  onSavePermissionMode: (mode: string) => Promise<boolean>
  devMode: boolean
  onSetDevMode: (enabled: boolean) => Promise<boolean>
  onClose: () => void
}

interface PluginEntry {
  name: string
  description: string
  category: string
  action_kind: string
  status: string
  error?: string
}

const PERMISSION_MODES: Array<{ value: string; label: string; desc: string }> = [
  { value: 'read_only', label: '只读', desc: '不改变世界：只能观察、搜索与推理' },
  { value: 'ask', label: '询问', desc: '每次变更操作先请求你的授权' },
  { value: 'auto_review', label: '自动审核', desc: '变更先经系统自动审核，通过才执行，不通过转询问' },
  { value: 'full', label: '完全权限', desc: '变更自动放行，不打断' },
]

export default function SettingsDialog({
  permissionMode,
  onSavePermissionMode,
  devMode,
  onSetDevMode,
  onClose,
}: SettingsDialogProps) {
  const current = permissionMode || 'ask'
  const select = (mode: string) => onSavePermissionMode(mode)

  const [plugins, setPlugins] = useState<PluginEntry[]>([])
  const [pluginsDir, setPluginsDir] = useState('')
  const [pluginBusy, setPluginBusy] = useState(false)
  const [pluginError, setPluginError] = useState('')

  const loadPlugins = async () => {
    setPluginBusy(true)
    setPluginError('')
    try {
      const response = await fetch('/api/v1/plugins')
      if (!response.ok) throw new Error('加载插件列表失败')
      const payload = await response.json()
      setPlugins(payload.plugins || [])
      setPluginsDir(payload.dir || '')
    } catch (cause) {
      setPluginError(cause instanceof Error ? cause.message : '加载插件列表失败')
    } finally {
      setPluginBusy(false)
    }
  }

  useEffect(() => {
    loadPlugins()
  }, [])

  const rescan = async () => {
    setPluginBusy(true)
    setPluginError('')
    try {
      const response = await fetch('/api/v1/plugins/scan', { method: 'POST' })
      if (!response.ok) throw new Error('扫描插件失败')
      await loadPlugins()
    } catch (cause) {
      setPluginError(cause instanceof Error ? cause.message : '扫描插件失败')
      setPluginBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
      onClick={onClose}
    >
      <div
        className="bg-cream rounded-xl border border-linen/60 shadow-2xl p-6 w-[440px] max-w-[92vw] max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-ink mb-4 font-display">⚙ 设置</h2>

        <div className="mb-2">
          <div className="text-sm font-medium text-ink">权限模式</div>
          <div className="text-xs text-warmgray mt-0.5 mb-3">
            决定智能体的变更操作如何被放行，保存后写入 config.toml [runtime]
          </div>
        </div>

        <div className="space-y-2 mb-6">
          {PERMISSION_MODES.map(mode => (
            <button
              key={mode.value}
              type="button"
              onClick={() => select(mode.value)}
              className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                current === mode.value
                  ? 'bg-seal border-seal text-white'
                  : 'bg-white border-linen text-ink hover:border-clay'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm">{mode.label}</span>
                <span className={`text-xs ${current === mode.value ? 'text-white/80' : 'text-warmgray'}`}>
                  {mode.value}
                </span>
              </div>
              <div className={`text-xs mt-1 ${current === mode.value ? 'text-white/85' : 'text-warmgray'}`}>
                {mode.desc}
              </div>
            </button>
          ))}
        </div>

        <label className="flex items-center justify-between cursor-pointer mb-6">
          <div>
            <div className="text-sm font-medium text-ink">开发者模式</div>
            <div className="text-xs text-warmgray mt-0.5">
              开启后可以看到各阶段 LLM 中间输出和原始追踪信息
            </div>
          </div>
          <button
            role="switch"
            aria-checked={devMode}
            onClick={() => onSetDevMode(!devMode)}
            className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ml-4 ${
              devMode ? 'bg-seal' : 'bg-clay'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow
                          transition-transform ${
                            devMode ? 'translate-x-5' : 'translate-x-0'
                          }`}
            />
          </button>
        </label>

        <div className="mb-2">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-ink">插件</div>
              <div className="text-xs text-warmgray mt-0.5">
                用户添加的非核心工具，放在 {pluginsDir || 'data/plugins'} 目录（manifest.yaml 声明）
              </div>
            </div>
            <button
              type="button"
              onClick={rescan}
              disabled={pluginBusy}
              className="px-3 py-1.5 rounded-lg bg-seal text-white text-xs font-semibold hover:bg-seal-light transition-colors flex-shrink-0 ml-3"
            >
              {pluginBusy ? '扫描中…' : '↻ 扫描'}
            </button>
          </div>
        </div>

        <div className="space-y-2 mb-6">
          {pluginError && <p className="form-error text-xs text-red-600">{pluginError}</p>}
          {plugins.length === 0 && !pluginBusy && (
            <div className="text-xs text-warmgray bg-dust rounded-lg px-3 py-2">（暂无插件）</div>
          )}
          {plugins.map(plugin => (
            <div
              key={plugin.name}
              className={`px-3 py-2 rounded-lg border text-xs ${
                plugin.status === 'loaded'
                  ? 'bg-white border-linen'
                  : 'bg-white border-red-300'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-ink">{plugin.name}</span>
                <span className={`text-[10px] ${plugin.status === 'loaded' ? 'text-seal' : 'text-red-500'}`}>
                  {plugin.status === 'loaded' ? `已加载 · ${plugin.category}` : '加载失败'}
                </span>
              </div>
              {plugin.description && (
                <div className="text-warmgray mt-0.5">{plugin.description}</div>
              )}
              {plugin.error && <div className="text-red-500 mt-0.5">{plugin.error}</div>}
            </div>
          ))}
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-warmgray hover:bg-dust transition-colors"
          >
            关闭
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-seal text-white text-sm font-semibold
                       hover:bg-seal-light transition-colors"
          >
            ✓ 完成
          </button>
        </div>
      </div>
    </div>
  )
}
