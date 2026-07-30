interface SettingsDialogProps {
  devMode: boolean
  onSetDevMode: (v: boolean) => void
  onClose: () => void
}

export default function SettingsDialog({ devMode, onSetDevMode, onClose }: SettingsDialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
      onClick={onClose}
    >
      <div
        className="bg-cream rounded-xl border border-linen/60 shadow-2xl p-6 w-[380px] max-w-[90vw]"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-ink mb-4 font-display">⚙ 设置</h2>

        <div className="space-y-4">
          <label className="flex items-center justify-between cursor-pointer">
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
        </div>

        <div className="flex justify-end gap-3 mt-6">
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
