import { useState, useMemo } from 'react'
import { PHASES, PHASE_ICONS, PHASE_LABELS } from '../types'
import type { TraceRecord } from '../types'

interface PhaseOutputPanelProps {
  records: TraceRecord[]
}

export default function PhaseOutputPanel({ records }: PhaseOutputPanelProps) {
  const [expandedPhase, setExpandedPhase] = useState<string | null>(null)

  // Group records by phase, keep latest iteration per phase
  const grouped = useMemo(() => {
    const map: Record<string, { records: TraceRecord[]; latest: TraceRecord | null }> = {}
    for (const r of records) {
      if (!map[r.phase]) map[r.phase] = { records: [], latest: null }
      map[r.phase].records.push(r)
      map[r.phase].latest = r
    }
    return map
  }, [records])

  const phaseIds = PHASES.map(p => p.id).filter(id => grouped[id])

  if (phaseIds.length === 0) return null

  return (
    <div className="card p-4">
      <h3 className="text-xs font-semibold text-seal mb-3 uppercase tracking-wide">
        📡 阶段中间输出
        <span className="text-warmgray font-normal ml-2 text-[10px]">
          开发者模式 · 可选中复制
        </span>
      </h3>

      <div className="space-y-3">
        {phaseIds.map(phaseId => {
          const group = grouped[phaseId]
          const latest = group!.latest!
          const icon = PHASE_ICONS[phaseId] || '📝'
          const label = PHASE_LABELS[phaseId] || phaseId
          const isExpanded = expandedPhase === phaseId

          // Truncate for preview
          const preview = latest.output.slice(0, 200)
          const needsExpand = latest.output.length > 200

          return (
            <div key={phaseId} className="bg-paper rounded-lg border border-linen/40 p-3">
              <button
                onClick={() => setExpandedPhase(isExpanded ? null : phaseId)}
                className="w-full text-left"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs
                               font-semibold bg-seal-wash text-seal"
                  >
                    {icon} {label}
                  </span>
                  {group!.records.length > 1 && (
                    <span className="text-[10px] text-warmgray">
                      第{group!.records.length}轮
                    </span>
                  )}
                  <span className="text-[10px] text-warmgray ml-auto">
                    #{latest.seq}
                  </span>
                </div>
              </button>

              <div className={`mt-2 text-sm text-ink leading-relaxed select-all
                              ${needsExpand && !isExpanded ? 'line-clamp-3' : ''}`}
              >
                {latest.output}
              </div>

              {needsExpand && (
                <button
                  onClick={() => setExpandedPhase(isExpanded ? null : phaseId)}
                  className="text-xs text-seal hover:text-seal-light mt-1"
                >
                  {isExpanded ? '收起' : `展开全部（共 ${latest.output.length} 字符）`}
                </button>
              )}

              {needsExpand && isExpanded && (
                <p className="text-[10px] text-warmgray mt-2">
                  💡 提示：框内文字可以鼠标选中复制
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
