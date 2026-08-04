interface SettingsDialogProps {
  permissionMode: string
  onSavePermissionMode: (mode: string) => Promise<boolean>
  devMode: boolean
  onSetDevMode: (enabled: boolean) => Promise<boolean>
  onClose: () => void
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
      onClick={onClose}
    >
      <div
        className="bg-cream rounded-xl border border-linen/60 shadow-2xl p-6 w-[420px] max-w-[90vw]"
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
