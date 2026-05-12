export type NodeStatus = 'unlit' | 'activated' | 'explored'
export type BlindspotType = 'adjacent' | 'missing_link' | 'shallow'
export type QuestionCategory = 'definition' | 'relation' | 'deepen' | 'explore' | 'application'

export interface NodeState {
  node_id: string
  name: string
  short_definition: string | null
  layer: string
  parent_id: string | null
  state: NodeStatus
  depth_score: number
  is_visible: boolean
  lit_at: string | null
  position_x: number
  position_y: number
  position_z: number
}

export interface EdgeState {
  edge_id: string
  source_node_id: string
  target_node_id: string
  relation_type: string
}

export interface GraphData {
  nodes: NodeState[]
  edges: EdgeState[]
}

export interface BlindspotItem {
  node_id: string
  blindspot_type: BlindspotType
  priority: number
  reason: string
}

export interface SuggestedQuestion {
  node_id: string
  category: QuestionCategory
  prompt: string
}

export interface SessionResponse {
  session_id: string
  topic: string
  graph: GraphData
  blindspots: BlindspotItem[]
  activated_count: number
  explored_count: number
  total_count: number
  coverage_percent: number
  created_at: string
}

export interface TurnItem {
  turn_id: string
  session_id: string
  speaker: string
  content: string
  timestamp: string
}

export interface MatchItem {
  node_id: string
  match_type: 'mention' | 'explain' | 'deepen'
  confidence: number
  depth_delta: number
}

export interface TurnResponse {
  turn_id: string
  ai_reply: string
  matches: MatchItem[]
  updated_nodes: NodeState[]
  visible_nodes: NodeState[]
  blindspots: BlindspotItem[]
  suggested_questions: SuggestedQuestion[]
}

export interface NodeSummaryResponse {
  node_id: string
  name: string
  short_definition: string
  summary: string
  source_turn_ids: string[]
}

export interface TraceTurn {
  turn_id: string
  speaker: string
  content: string
  timestamp: string
}

export interface NodeTraceResponse {
  node_id: string
  turns: TraceTurn[]
}

export interface ExpandResponse {
  node_id: string
  activated: boolean
  revealed_nodes: NodeState[]
}

export interface QuestionsResponse {
  node_id: string
  questions: SuggestedQuestion[]
}

export interface ExperimentEventPayload {
  event_type: string
  node_id?: string | null
  turn_id?: string | null
  question_category?: QuestionCategory | null
  duration_ms?: number | null
  metadata?: Record<string, unknown>
}

export interface ExperimentEventItem extends ExperimentEventPayload {
  event_id: string
  session_id: string
  created_at: string
}

export interface GraphSnapshotItem {
  snapshot_id: string
  session_id: string
  label: string | null
  active_count: number
  activated_count: number
  explored_count: number
  total_count: number
  explored_active_percent: number
  coverage_percent: number
  blindspots: BlindspotItem[]
  graph: GraphData
  created_at: string
}
