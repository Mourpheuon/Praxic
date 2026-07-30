import { useState, useCallback, useRef, FormEvent } from 'react'
import type { RunStatus } from '../types'

interface QuestionCardProps {
  onRun: (question: string, context: string, mode: string, files: string[]) => void
  onStop: () => void
  status: RunStatus
  projectId: string
}

const EXAMPLE_QUESTIONS = [
  '为什么开源项目难以吸引贡献者？',
  '如何用有限资源快速构建 MVP？',
  '微服务 vs 单体架构如何选择？',
  '为什么好产品用户留存率仍然很低？',
]

export default function QuestionCard({ onRun, onStop, status, projectId }: QuestionCardProps) {
  const [question, setQuestion] = useState('')
  const [context, setContext] = useState('')
  const [mode, setMode] = useState('standard')
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const running = status === 'running'
  const busy = running || uploading

  const uploadFiles = useCallback(async (files: File[]): Promise<string[]> => {
    const paths: string[] = []
    for (const file of files) {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('project_id', projectId)
      try {
        const res = await fetch('/api/v1/agent/upload-file', { method: 'POST', body: formData })
        const data = await res.json()
        if (data.ok && data.file_path) paths.push(data.file_path)
      } catch (e) {
        console.error('上传失败:', file.name, e)
      }
    }
    return paths
  }, [projectId])

  const handleSubmit = useCallback(async (e?: FormEvent) => {
    e?.preventDefault()
    if (!question.trim() || busy) return
    let filePaths: string[] = []
    if (selectedFiles.length > 0) {
      setUploading(true)
      filePaths = await uploadFiles(selectedFiles)
      setUploading(false)
    }
    onRun(question.trim(), context.trim(), mode, filePaths)
  }, [question, context, mode, selectedFiles, busy, onRun, uploadFiles])

  return (
    <form onSubmit={handleSubmit} className="card p-5 space-y-4">
      <h2 className="text-base font-semibold text-ink">提出问题</h2>

      <div>
        <textarea
          value={question}
          onChange={e => setQuestion(e.target.value)}
          placeholder="例如：为什么我的开源项目很难吸引贡献者？"
          rows={4}
          disabled={running}
          className="w-full bg-paper border border-linen/60 rounded-lg px-4 py-3 text-sm text-ink
                     placeholder:text-clay focus:outline-none focus:border-seal/50 focus:ring-1 focus:ring-seal/20
                     disabled:opacity-50 resize-none font-body"
        />
      </div>

      <div>
        <textarea
          value={context}
          onChange={e => setContext(e.target.value)}
          placeholder="提供额外的背景信息…"
          rows={2}
          disabled={running}
          className="w-full bg-paper border border-linen/60 rounded-lg px-4 py-3 text-sm text-ink
                     placeholder:text-clay focus:outline-none focus:border-seal/50 focus:ring-1 focus:ring-seal/20
                     disabled:opacity-50 resize-none font-body"
        />
      </div>

      {/* 文件上传 */}
      <div>
        <label className="text-xs font-semibold text-warmgray mb-1.5 block">
          📎 附加文件（可选）
        </label>
        <div
          className="border-2 border-dashed border-linen/60 rounded-lg p-3
                     hover:border-seal/40 transition-colors cursor-pointer"
          onClick={() => { if (!busy) fileInputRef.current?.click() }}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            disabled={busy}
            onChange={e => {
              if (e.target.files) {
                setSelectedFiles(prev => [...prev, ...Array.from(e.target.files as FileList)])
              }
              e.target.value = ''
            }}
            className="hidden"
            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.py,.json,.csv,.html,.js,.ts,.jsx,.tsx,.ipynb,.yaml,.yml,.xml"
          />
          {selectedFiles.length === 0 ? (
            <p className="text-sm text-clay text-center">
              点击选择文件（支持 PDF / DOCX / XLSX / TXT / PY 等）
            </p>
          ) : (
            <div className="space-y-1">
              {selectedFiles.map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-sm text-ink/80">
                  <span className="truncate flex-1">{f.name}</span>
                  <span className="text-xs text-clay flex-shrink-0">
                    {(f.size / 1024).toFixed(0)} KB
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation()
                      setSelectedFiles(prev => prev.filter((_, j) => j !== i))
                    }}
                    className="text-clay hover:text-seal flex-shrink-0 disabled:opacity-40"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <select
          value={mode}
          onChange={e => setMode(e.target.value)}
          disabled={running}
          className="bg-paper border border-linen/60 rounded-lg px-3 py-2 text-sm text-ink
                     focus:outline-none focus:border-seal/50 cursor-pointer font-body disabled:opacity-50"
        >
          <option value="fast">⚡ 快速模式</option>
          <option value="standard">🔄 标准模式</option>
          <option value="deep">🔬 深度模式</option>
        </select>

        {running ? (
          <button
            type="button"
            onClick={onStop}
            className="px-5 py-2 rounded-lg bg-warmgray text-white text-sm font-semibold
                       hover:bg-warmgray/80 transition-colors"
          >
            ⛔ 终止
          </button>
        ) : (
          <button
            type="submit"
            disabled={!question.trim() || uploading}
            className="px-5 py-2 rounded-lg bg-seal text-white text-sm font-semibold
                       hover:bg-seal-light transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? '⏳ 上传中…' : '🚀 开始分析'}
          </button>
        )}
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        {EXAMPLE_QUESTIONS.map(q => (
          <button
            key={q}
            type="button"
            disabled={running}
            onClick={() => setQuestion(q)}
            className="px-3 py-1.5 rounded-full bg-dust border border-clay/40 text-xs text-warmgray
                       hover:bg-clay/30 hover:text-ink transition-colors disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </form>
  )
}
