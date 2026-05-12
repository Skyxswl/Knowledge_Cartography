import type {
  BlindspotItem,
  EdgeState,
  ExpandResponse,
  NodeState,
  SessionResponse,
  SuggestedQuestion,
  TraceTurn,
  TurnResponse,
} from '@/api/types'

export interface GraphState {
  sessionId: string
  topic: string
  nodes: NodeState[]
  edges: EdgeState[]
  blindspots: BlindspotItem[]
  suggestedQuestions: SuggestedQuestion[]
  selectedNodeId: string | null
  traceTurns: TraceTurn[]
  recentUpdateNodeIds: string[]
  activatedCount: number
  exploredCount: number
  totalCount: number
  coveragePercent: number
}

function mergeNodes(current: NodeState[], incoming: NodeState[]): NodeState[] {
  const map = new Map(current.map((node) => [node.node_id, node]))
  for (const node of incoming) {
    map.set(node.node_id, { ...map.get(node.node_id), ...node })
  }
  return Array.from(map.values())
}

function buildQuestionOptions(node: NodeState | undefined, blindspots: BlindspotItem[]): SuggestedQuestion[] {
  if (!node) {
    const firstBlindspot = blindspots[0]
    if (!firstBlindspot) return []
    return [
      {
        node_id: firstBlindspot.node_id,
        category: 'relation',
        prompt: '为什么这个盲区会出现在当前讨论附近？它和我已经触达的概念有什么联系？',
      },
    ]
  }

  return [
    {
      node_id: node.node_id,
      category: 'definition',
      prompt: `请先用一句话定义「${node.name}」，再解释它在当前主题里的位置。`,
    },
    {
      node_id: node.node_id,
      category: 'relation',
      prompt: `请解释「${node.name}」和当前最相关概念之间的关系与区别。`,
    },
    {
      node_id: node.node_id,
      category: 'deepen',
      prompt: `请进一步展开「${node.name}」的机制、影响和一个具体例子。`,
    },
  ]
}

function countGraphProgress(nodes: NodeState[]) {
  const activatedCount = nodes.filter((node) => node.state !== 'unlit').length
  const exploredCount = nodes.filter((node) => node.state === 'explored').length
  const totalCount = nodes.length
  return {
    activatedCount,
    exploredCount,
    totalCount,
    coveragePercent: totalCount > 0 ? Math.round((exploredCount / totalCount) * 1000) / 10 : 0,
  }
}

export type GraphAction =
  | { type: 'INIT_GRAPH'; payload: SessionResponse }
  | { type: 'APPLY_TURN'; payload: TurnResponse }
  | { type: 'APPLY_EXPAND'; payload: ExpandResponse }
  | { type: 'SELECT_NODE'; payload: string | null }
  | { type: 'SET_SUGGESTED_QUESTIONS'; payload: SuggestedQuestion[] }
  | {
      type: 'RESTORE_PANEL_STATE'
      payload: {
        selectedNodeId: string | null
        suggestedQuestions: SuggestedQuestion[]
        traceTurns: TraceTurn[]
      }
    }
  | { type: 'SET_TRACE_TURNS'; payload: TraceTurn[] }

export function graphReducer(state: GraphState, action: GraphAction): GraphState {
  switch (action.type) {
    case 'INIT_GRAPH': {
      const progress = countGraphProgress(action.payload.graph.nodes)
      return {
        sessionId: action.payload.session_id,
        topic: action.payload.topic,
        nodes: action.payload.graph.nodes,
        edges: action.payload.graph.edges,
        blindspots: action.payload.blindspots,
        suggestedQuestions: [],
        selectedNodeId: null,
        traceTurns: [],
        recentUpdateNodeIds: [],
        ...progress,
      }
    }

    case 'APPLY_TURN': {
      const updatedNodes = action.payload.updated_nodes ?? []
      const visibleNodes = action.payload.visible_nodes ?? []
      const blindspots = action.payload.blindspots ?? []
      const suggestedQuestions = action.payload.suggested_questions ?? []
      const mergedNodes = mergeNodes(state.nodes, [...updatedNodes, ...visibleNodes])
      const progress = countGraphProgress(mergedNodes)
      return {
        ...state,
        nodes: mergedNodes,
        blindspots,
        suggestedQuestions,
        recentUpdateNodeIds: updatedNodes.map((node) => node.node_id),
        ...progress,
      }
    }

    case 'APPLY_EXPAND': {
      const expandedNode = state.nodes.find((node) => node.node_id === action.payload.node_id)
      const localExpandedNode = expandedNode
        ? {
            ...expandedNode,
            state: 'activated' as const,
            depth_score: Math.max(expandedNode.depth_score, 0.15),
            is_visible: true,
            lit_at: expandedNode.lit_at ?? new Date().toISOString(),
          }
        : null
      const incomingNodes = localExpandedNode
        ? [localExpandedNode, ...(action.payload.revealed_nodes ?? [])]
        : action.payload.revealed_nodes ?? []
      const mergedNodes = mergeNodes(state.nodes, incomingNodes)
      const progress = countGraphProgress(mergedNodes)
      return {
        ...state,
        nodes: mergedNodes,
        recentUpdateNodeIds: incomingNodes.map((node) => node.node_id),
        ...progress,
      }
    }

    case 'SELECT_NODE': {
      const selectedNode = state.nodes.find((node) => node.node_id === action.payload)
      return {
        ...state,
        selectedNodeId: action.payload,
        suggestedQuestions: buildQuestionOptions(selectedNode, state.blindspots),
      }
    }

    case 'RESTORE_PANEL_STATE':
      return {
        ...state,
        selectedNodeId: action.payload.selectedNodeId,
        suggestedQuestions: action.payload.suggestedQuestions,
        traceTurns: action.payload.traceTurns,
      }

    case 'SET_TRACE_TURNS':
      return {
        ...state,
        traceTurns: action.payload,
      }

    case 'SET_SUGGESTED_QUESTIONS':
      return {
        ...state,
        suggestedQuestions: action.payload,
      }

    default:
      return state
  }
}

export const INITIAL_GRAPH_STATE: GraphState = {
  sessionId: '',
  topic: '',
  nodes: [],
  edges: [],
  blindspots: [],
  suggestedQuestions: [],
  selectedNodeId: null,
  traceTurns: [],
  recentUpdateNodeIds: [],
  activatedCount: 0,
  exploredCount: 0,
  totalCount: 0,
  coveragePercent: 0,
}
