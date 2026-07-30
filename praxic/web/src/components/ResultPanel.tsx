interface ResultPanelProps {
  summary: string
  actions: string[]
}

export default function ResultPanel({ summary, actions }: ResultPanelProps) {
  // inline: **bold**
  const renderInline = (text: string) => {
    const segs = text.split(/(\*\*[^*]+\*\*)/g)
    return segs.map((seg, j) =>
      seg.startsWith('**') && seg.endsWith('**')
        ? <strong key={j} className="font-semibold text-ink">{seg.slice(2, -2)}</strong>
        : <span key={j}>{seg}</span>
    )
  }

  // Simple markdown-like rendering for the summary
  const renderSummary = (text: string) => {
    const lines = text.split('\n')
    return lines.map((line, i) => {
      if (line.startsWith('### ')) {
        return <h3 key={i} className="text-base font-semibold text-ink mt-3 mb-1 font-display">{renderInline(line.slice(4))}</h3>
      }
      if (line.startsWith('## ')) {
        return <h2 key={i} className="text-lg font-semibold text-ink mt-4 mb-2 font-display">{renderInline(line.slice(3))}</h2>
      }
      if (line.startsWith('# ')) {
        return <h1 key={i} className="text-xl font-bold text-ink mt-4 mb-2 font-display">{renderInline(line.slice(2))}</h1>
      }
      const om = line.match(/^(\d+)\.\s+(.*)$/)
      if (om) {
        return (
          <div key={i} className="ml-4 flex gap-2 text-sm text-ink leading-relaxed">
            <span className="font-semibold flex-shrink-0">{om[1]}.</span>
            <span>{renderInline(om[2])}</span>
          </div>
        )
      }
      if (line.startsWith('- ')) {
        return (
          <div key={i} className="ml-4 flex gap-2 text-sm text-ink leading-relaxed">
            <span className="flex-shrink-0">•</span>
            <span>{renderInline(line.slice(2))}</span>
          </div>
        )
      }
      if (line.startsWith('> ')) {
        return <blockquote key={i} className="border-l-2 border-seal pl-3 italic text-warmgray text-sm my-1">{renderInline(line.slice(2))}</blockquote>
      }
      if (line.trim() === '') {
        return <div key={i} className="h-2" />
      }
      return <p key={i} className="text-sm text-ink leading-relaxed">{renderInline(line)}</p>
    })
  }

  return (
    <div className="card p-5">
      <div className="flex flex-col lg:flex-row gap-5">
        {/* Summary */}
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-ink mb-3">📋 最终结论</h3>
          <div className="bg-paper rounded-lg border border-linen/40 p-4 prose max-w-none select-all">
            {renderSummary(summary)}
          </div>
        </div>

        {/* Action items */}
        <div className="w-full lg:w-72 flex-shrink-0">
          <h3 className="text-sm font-semibold text-ink mb-3">✅ 行动建议</h3>
          <div className="bg-paper rounded-lg border border-linen/40 p-3 space-y-2">
            {actions.length === 0 ? (
              <p className="text-sm text-warmgray">暂无行动建议</p>
            ) : (
              actions.map((action, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-seal-wash text-seal
                                   text-xs font-bold flex items-center justify-center">
                    {i + 1}
                  </span>
                  <p className="text-sm text-ink leading-relaxed pt-0.5">{action}</p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
