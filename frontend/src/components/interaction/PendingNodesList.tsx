import { useGraph } from '@/store/GraphContext'

interface PendingNodesListProps {
  onNodeClick: (nodeId: string, nodeName: string) => void
}

export default function PendingNodesList({ onNodeClick }: PendingNodesListProps) {
  const { state } = useGraph()
  const pendingNodes = state.nodes.filter((node) => node.state === 'unlit')

  if (pendingNodes.length === 0) {
    return <div className="text-sm italic text-slate-400">当前可见区域已经全部触达。</div>
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="mb-1 text-sm font-medium text-slate-600">未触达节点 ({pendingNodes.length})</div>
      <div className="flex flex-wrap gap-2">
        {pendingNodes.slice(0, 8).map((node) => (
          <button
            key={node.node_id}
            onClick={() => onNodeClick(node.node_id, node.name)}
            className="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-600 transition-colors hover:border-cyan-400 hover:text-cyan-700"
          >
            {node.name}
          </button>
        ))}
      </div>
    </div>
  )
}
