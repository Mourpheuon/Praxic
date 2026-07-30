import { PHASES } from '../types'
import type { PhaseId } from '../types'

interface PhaseTimelineProps {
  activePhase: PhaseId | null
  completedPhases: Set<string>
  loadingText: string
}

export default function PhaseTimeline({
  activePhase,
  completedPhases,
  loadingText,
}: PhaseTimelineProps) {
  return (
    <div className="card p-4">
      <h3 className="text-xs font-semibold text-warmgray mb-3 uppercase tracking-wide">
        认知过程
      </h3>

      <div className="flex gap-2 overflow-x-auto scrollbar-thin pb-1">
        {PHASES.map(phase => {
          const isActive = activePhase === phase.id
          const isDone = completedPhases.has(phase.id)

          let bg = 'bg-dust'
          let border = 'border-clay/40'
          let textColor = 'text-clay'

          if (isActive) {
            bg = 'bg-seal-wash'
            border = 'border-seal'
            textColor = 'text-seal'
          } else if (isDone) {
            bg = 'bg-olivewash'
            border = 'border-olive/40'
            textColor = 'text-olive'
          }

          return (
            <div
              key={phase.id}
              className={`flex-shrink-0 w-[110px] rounded-lg border-2 ${bg} ${border} p-3
                          text-center transition-all duration-300`}
            >
              <div className="text-lg mb-1">{phase.icon}</div>
              <div className={`text-xs font-medium ${textColor}`}>{phase.label}</div>
              {isActive && loadingText && (
                <div className="text-[10px] text-seal-light mt-1 animate-pulse">
                  ···
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
