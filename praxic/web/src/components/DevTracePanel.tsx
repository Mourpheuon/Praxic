import { useState } from 'react'
import { PHASE_LABELS } from '../types'
import type { TraceRecord } from '../types'

interface DevTracePanelProps {
  records: TraceRecord[]
}

export default function DevTracePanel({ records }: DevTracePanelProps) {
  const [expanded, setExpanded] = useState(false)

  if (records.length === 0) return null

  const visibleRecords = expanded ? records : records.slice(-5)

  return (
    <div className="card p-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
      >
        <h3 className="text-xs font-semibold text-seal uppercase tracking-wide">
          📡 LLM 原始输出
        </h3>
        <span className="text-[10px] text-warmgray ml-auto">
          {records.length} 条记录
          {expanded ? ' ▲ 收起' : ' ▼ 展开'}
        </span>
      </button>

      <div className={`space-y-2 ${expanded ? 'mt-3' : 'mt-2'}`}>
        {visibleRecords.map((rec, i) => {
          const label = PHASE_LABELS[rec.phase] || rec.phase
          const header = `#${rec.seq} ${label}` + (rec.tag ? ` · ${rec.tag}` : '')
          const display = rec.output.slice(0, 2000)

          return (
            <div key={i} className="bg-paper rounded-lg border border-linen/40 p-3">
              <div className="text-xs font-semibold text-seal mb-1.5">{header}</div>
              <pre className="text-[11px] text-ink font-mono whitespace-pre-wrap break-all
                              bg-cream rounded-md p-2.5 max-h-60 overflow-y-auto scrollbar-thin">
                {display}
                {rec.output.length > 2000 && (
                  <span className="text-warmgray">
                    {'\n\n'}... [截断，共 {rec.output.length} 字符]
                  </span>
                )}
              </pre>
            </div>
          )
        })}
      </div>
    </div>
  )
}
