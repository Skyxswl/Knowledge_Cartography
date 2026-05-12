import type { SuggestedQuestion } from '@/api/types'
import SimpleMarkdown, { stripMarkdown } from '@/components/common/SimpleMarkdown'
import { useGraph } from '@/store/GraphContext'

interface NodeInteractionPanelProps {
  activeTurnId: string | null
  isSending: boolean
  pendingQuestionPrompt: string | null
  onBlindspotSelect: (nodeId: string) => void
  onQuestionFill: (question: SuggestedQuestion) => void
  onQuestionSend: (question: SuggestedQuestion) => void
  onTraceSelect: (turnId: string) => void
}

function summarizeTraceContent(content: string, maxLength = 118) {
  const compact = stripMarkdown(content).replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) return compact
  return `${compact.slice(0, maxLength).trimEnd()}…`
}

export default function NodeInteractionPanel({
  activeTurnId,
  isSending,
  pendingQuestionPrompt,
  onBlindspotSelect,
  onQuestionFill,
  onQuestionSend,
  onTraceSelect,
}: NodeInteractionPanelProps) {
  const { state } = useGraph()
  const blindspots = state.blindspots ?? []
  const suggestedQuestions = state.suggestedQuestions ?? []
  const traceTurns = state.traceTurns ?? []
  const nodes = state.nodes ?? []
  const activatedCount = state.activatedCount ?? 0
  const exploredCount = state.exploredCount ?? 0
  const totalCount = state.totalCount ?? 0
  const coveragePercent = state.coveragePercent ?? 0
  const touchedPercent = totalCount > 0 ? Math.round((activatedCount / totalCount) * 1000) / 10 : 0
  const activeTraceTurn = traceTurns.find((turn) => turn.turn_id === activeTurnId) ?? traceTurns[0] ?? null

  return (
    <div className="flex min-h-full flex-col gap-2.5 bg-[linear-gradient(180deg,#ffffff_0%,#f8fbff_100%)] p-3">
      <section className="rounded-2xl border border-slate-200/90 bg-[linear-gradient(180deg,#fcfdff_0%,#f7fbff_100%)] px-4 py-3 shadow-[0_10px_30px_rgba(15,23,42,0.05)]">
        <div className="flex items-center justify-between text-sm text-slate-600">
          <span className="font-medium text-slate-700">当前理解区</span>
          <span className="rounded-full border border-cyan-100 bg-cyan-50 px-2.5 py-0.5 font-medium text-cyan-800">
            {exploredCount} / {totalCount} 已深入
          </span>
        </div>
        <div className="relative mt-2 h-2.5 overflow-hidden rounded-full bg-slate-200">
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-cyan-200 transition-all duration-500"
            style={{ width: `${touchedPercent}%` }}
          />
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-cyan-600 transition-all duration-500"
            style={{ width: `${coveragePercent}%` }}
          />
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
          <span>
            {activatedCount > 0
              ? `已触达 ${activatedCount} 个概念，已深入 ${exploredCount} 个`
              : '暂无结构命中，等待下一轮对话点亮图谱'}
          </span>
          <span>{coveragePercent}% 已深入</span>
        </div>

        <div className="mt-3 mb-2 flex items-center justify-between border-t border-slate-200/80 pt-3">
          <div className="text-sm font-semibold text-slate-900">Blindspots</div>
          <div className="rounded-full border border-amber-100 bg-amber-50 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-amber-700">
            {blindspots.length}
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {blindspots.length === 0 && (
            <div className="text-xs text-slate-400">
              {activatedCount > 0 ? '当前没有明显盲区，继续深化可生成断点。' : '首个概念命中后，这里会显示附近盲区。'}
            </div>
          )}
          {blindspots.slice(0, 2).map((item) => {
            const node = nodes.find((entry) => entry.node_id === item.node_id)
            return (
              <button
                key={`${item.node_id}-${item.blindspot_type}`}
                onClick={() => onBlindspotSelect(item.node_id)}
                className="rounded-xl border border-slate-200 px-3 py-2 text-left transition hover:border-cyan-400 hover:bg-cyan-50"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-900">{node?.name ?? item.node_id}</span>
                  <span className="text-[11px] uppercase tracking-wide text-cyan-700">{item.blindspot_type}</span>
                </div>
                <div className="mt-1 text-xs text-slate-500">{item.reason}</div>
              </button>
            )
          })}
          {blindspots.length > 2 && (
            <div className="rounded-xl border border-dashed border-amber-200 bg-amber-50/50 px-3 py-1.5 text-xs text-amber-700">
              还有 {blindspots.length - 2} 个盲区，优先处理上方两项或点击图谱岛屿查看。
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200/90 bg-white/90 p-2.5 shadow-[0_8px_24px_rgba(15,23,42,0.04)]">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-900">Suggested Questions</div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            推荐动作
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {suggestedQuestions.length === 0 && (
            <div className="text-xs text-slate-400">
              {activatedCount > 0 ? '点击已触达岛屿或盲区，生成下一步问题。' : '当前还没有结构命中，继续提问后会生成建议问题。'}
            </div>
          )}
          {suggestedQuestions.map((question) => (
            <div
              key={`${question.node_id}-${question.category}`}
              className="rounded-xl border border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#fbfdff_100%)] px-3 py-2 transition hover:border-cyan-400 hover:bg-cyan-50"
            >
              <div className="text-[11px] uppercase tracking-wide text-cyan-700">{question.category}</div>
              <div className="mt-1 text-sm text-slate-800">{question.prompt}</div>
              <div className="mt-2 flex gap-2 border-t border-slate-100 pt-2">
                <button
                  onClick={() => onQuestionSend(question)}
                  disabled={isSending}
                  className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
                >
                  {isSending && pendingQuestionPrompt === question.prompt ? '发送中…' : '一键发送'}
                </button>
                <button
                  onClick={() => onQuestionFill(question)}
                  disabled={isSending}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:border-cyan-400 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  填入输入框
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200/90 bg-white/90 p-2.5 shadow-[0_8px_24px_rgba(15,23,42,0.04)]">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-900">Trace</div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            问答回溯
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {traceTurns.length === 0 && <div className="text-xs text-slate-400">选择一个节点后，这里会显示相关对话回溯。</div>}
          {traceTurns.map((turn) => (
            <button
              key={turn.turn_id}
              onClick={() => onTraceSelect(turn.turn_id)}
              className={`rounded-xl border px-3 py-2 text-left transition hover:border-cyan-400 hover:bg-cyan-50 ${
                turn.turn_id === activeTurnId ? 'border-cyan-400 bg-cyan-50/70' : 'border-slate-200'
              }`}
            >
              <div className="text-[11px] uppercase tracking-wide text-cyan-700">{turn.speaker}</div>
              <div className="mt-1 text-sm text-slate-700">{summarizeTraceContent(turn.content)}</div>
            </button>
          ))}
        </div>
        {activeTraceTurn && (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
            <div className="mb-2 text-[11px] uppercase tracking-wide text-cyan-700">
              当前查看 · {activeTraceTurn.speaker}
            </div>
            <SimpleMarkdown
              content={activeTraceTurn.content}
              className="[&_h1]:text-slate-900 [&_h2]:text-slate-900 [&_h3]:text-slate-900 [&_p]:text-slate-700 [&_strong]:text-slate-900 [&_blockquote]:not-italic"
            />
          </div>
        )}
      </section>
    </div>
  )
}
