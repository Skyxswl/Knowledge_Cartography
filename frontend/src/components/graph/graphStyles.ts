import type { NodeState } from '@/api/types'

export const GRAPH_COLORS = {
  canvas: '#F8F8F6',
  node: '#378ADD',
  nodeStroke: '#185FA5',
  edge: '#B5D4F4',
  label: '#3d3d3a',
  cluster: '#B5D4F4',
}

export function conceptNodeOpacity(node: NodeState) {
  if (!node.is_visible) return 0.12
  if (node.state === 'explored') return 0.9
  if (node.state === 'activated') return 0.5
  return Math.max(0.12, 0.15 + node.depth_score * 0.15)
}

export function conceptNodeRadius(node: NodeState) {
  const baseRadius = node.state === 'explored' ? 18 : node.state === 'activated' ? 13 : 8
  if (node.layer === '0') return baseRadius + 3
  return baseRadius
}

export function conceptLabelSize(node: NodeState) {
  if (node.state === 'explored') return 14
  if (node.state === 'activated') return 12
  return 10
}

export function clusterOpacity(depthScore: number) {
  if (depthScore > 0.6) return 0.35
  if (depthScore >= 0.3) return 0.2
  return 0.08
}
