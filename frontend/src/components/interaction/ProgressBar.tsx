import { useGraph } from '@/store/GraphContext'

export default function ProgressBar() {
  const { state } = useGraph()

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600">已探索范围</span>
        <span className="font-medium text-slate-900">
          {state.exploredCount} / {state.totalCount}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full rounded-full bg-cyan-500 transition-all duration-500"
          style={{ width: `${state.coveragePercent}%` }}
        />
      </div>
      <div className="text-right text-xs text-slate-500">{state.coveragePercent}% explored</div>
    </div>
  )
}
