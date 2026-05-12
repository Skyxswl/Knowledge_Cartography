import {
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type WheelEvent as ReactWheelEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { getNodeSummary } from '@/api/sessions'
import type { EdgeState, NodeState } from '@/api/types'
import { useGraph } from '@/store/GraphContext'
import { GRAPH_COLORS, clusterOpacity, conceptLabelSize, conceptNodeOpacity, conceptNodeRadius } from './graphStyles'

interface HoveredNode {
  nodeId: string
  name: string
  shortDefinition: string
  summary?: string
  x: number
  y: number
}

interface GraphViewerProps {
  onNodeClick?: (nodeId: string) => void
  onNodeHover?: (nodeId: string, durationMs: number) => void
}

interface ViewportTransform {
  x: number
  y: number
  scale: number
}

interface FieldDragState {
  active: boolean
  startX: number
  startY: number
  originX: number
  originY: number
  moved: boolean
}

interface FieldNode {
  node: NodeState
  x: number
  y: number
  radius: number
  anchorX: number
  anchorY: number
  collisionRadius: number
  layoutPriority: number
}

interface Point {
  x: number
  y: number
}

interface KnowledgeCluster {
  id: string
  path: string
  opacity: number
}

const DEFAULT_VIEWPORT_TRANSFORM: ViewportTransform = { x: 0, y: 0, scale: 1 }
const MIN_FIELD_SCALE = 0.72
const MAX_FIELD_SCALE = 1.8
const PAN_CLICK_THRESHOLD = 4
const Z_TO_X_WEIGHT = 0.14
const Z_TO_Y_WEIGHT = 0.32
const LAYOUT_RELAX_ITERATIONS = 30
const CENTER_SOFT_LIMIT = 46
const CLUSTER_PADDING = 46

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function nodeLayoutPriority(node: NodeState, selectedNodeId: string | null, recentUpdateNodeIds: string[]) {
  if (node.node_id === selectedNodeId) return 1.7
  if (recentUpdateNodeIds.includes(node.node_id)) return 1.55
  if (node.state === 'explored') return 1.45
  if (node.state === 'activated') return 1.32
  if (node.layer === '0') return 1.24
  if (node.is_visible) return 1.08
  return 0.62
}

function nodeCollisionRadius(node: NodeState, radius: number) {
  const visibleWeight = node.is_visible ? 1.9 : 1.35
  const stateWeight = node.state === 'explored' ? 1.18 : node.state === 'activated' ? 1.08 : 1
  return radius * visibleWeight * stateWeight
}

function collisionGap(source: FieldNode, target: FieldNode) {
  if (source.node.is_visible || target.node.is_visible) return 24
  if (source.node.state !== 'unlit' || target.node.state !== 'unlit') return 18
  return 10
}

function clampToField(node: FieldNode, width: number, height: number) {
  const margin = clamp(node.collisionRadius + 16, 24, 88)
  node.x = clamp(node.x, margin, width - margin)
  node.y = clamp(node.y, margin, height - margin)

  if (node.node.layer === '0') {
    const dx = node.x - node.anchorX
    const dy = node.y - node.anchorY
    const distance = Math.hypot(dx, dy)
    if (distance > CENTER_SOFT_LIMIT) {
      node.x = node.anchorX + (dx / distance) * CENTER_SOFT_LIMIT
      node.y = node.anchorY + (dy / distance) * CENTER_SOFT_LIMIT
    }
  }
}

function relaxFieldNodes(projectedNodes: FieldNode[], width: number, height: number) {
  const relaxedNodes = projectedNodes.map((entry) => ({ ...entry }))

  for (let iteration = 0; iteration < LAYOUT_RELAX_ITERATIONS; iteration += 1) {
    for (let sourceIndex = 0; sourceIndex < relaxedNodes.length; sourceIndex += 1) {
      for (let targetIndex = sourceIndex + 1; targetIndex < relaxedNodes.length; targetIndex += 1) {
        const source = relaxedNodes[sourceIndex]
        const target = relaxedNodes[targetIndex]
        const dx = target.x - source.x
        const dy = target.y - source.y
        const distance = Math.max(0.01, Math.hypot(dx, dy))
        const minDistance = source.collisionRadius + target.collisionRadius + collisionGap(source, target)

        if (distance >= minDistance) continue

        const overlap = (minDistance - distance) * 0.58
        const ux = dx / distance
        const uy = dy / distance
        const priorityTotal = source.layoutPriority + target.layoutPriority
        const sourceMove = target.layoutPriority / priorityTotal
        const targetMove = source.layoutPriority / priorityTotal

        source.x -= ux * overlap * sourceMove
        source.y -= uy * overlap * sourceMove
        target.x += ux * overlap * targetMove
        target.y += uy * overlap * targetMove
      }
    }

    for (const entry of relaxedNodes) {
      const anchorStrength = entry.node.layer === '0' ? 0.022 : entry.node.is_visible ? 0.012 : 0.006
      entry.x += (entry.anchorX - entry.x) * anchorStrength
      entry.y += (entry.anchorY - entry.y) * anchorStrength
      clampToField(entry, width, height)
    }
  }

  return relaxedNodes
}

function buildFieldNodes(nodes: NodeState[], width: number, height: number, selectedNodeId: string | null, recentUpdateNodeIds: string[]) {
  if (!nodes.length) return []

  const projected = nodes.map((node) => ({
    node,
    x: node.position_x + node.position_z * Z_TO_X_WEIGHT,
    y: node.position_y + node.position_z * Z_TO_Y_WEIGHT,
  }))
  const xs = projected.map((entry) => entry.x)
  const ys = projected.map((entry) => entry.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = Math.max(1, maxX - minX)
  const spanY = Math.max(1, maxY - minY)
  const paddingX = width * 0.1
  const paddingY = height * 0.1

  const fieldNodes = projected.map(({ node, x, y }) => {
    const px = paddingX + ((x - minX) / spanX) * (width - paddingX * 2)
    const py = paddingY + (1 - (y - minY) / spanY) * (height - paddingY * 2)
    const radius = conceptNodeRadius(node)
    return {
      node,
      x: px,
      y: py,
      radius,
      anchorX: px,
      anchorY: py,
      collisionRadius: nodeCollisionRadius(node, radius),
      layoutPriority: nodeLayoutPriority(node, selectedNodeId, recentUpdateNodeIds),
    }
  })

  return relaxFieldNodes(fieldNodes, width, height)
}

function cross(origin: Point, left: Point, right: Point) {
  return (left.x - origin.x) * (right.y - origin.y) - (left.y - origin.y) * (right.x - origin.x)
}

function convexHull(points: Point[]) {
  const sorted = [...points].sort((a, b) => (a.x === b.x ? a.y - b.y : a.x - b.x))
  if (sorted.length <= 1) return sorted

  const lower: Point[] = []
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) {
      lower.pop()
    }
    lower.push(point)
  }

  const upper: Point[] = []
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const point = sorted[index]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) {
      upper.pop()
    }
    upper.push(point)
  }

  lower.pop()
  upper.pop()
  return lower.concat(upper)
}

function smoothClosedPath(points: Point[]) {
  if (points.length < 3) return ''

  let path = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`
  for (let index = 0; index < points.length; index += 1) {
    const p0 = points[(index - 1 + points.length) % points.length]
    const p1 = points[index]
    const p2 = points[(index + 1) % points.length]
    const p3 = points[(index + 2) % points.length]
    const cp1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 }
    const cp2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 }
    path += ` C ${cp1.x.toFixed(2)} ${cp1.y.toFixed(2)}, ${cp2.x.toFixed(2)} ${cp2.y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`
  }
  return `${path} Z`
}

function expandedClusterPoints(nodes: FieldNode[]) {
  const points: Point[] = []
  const angles = [0, Math.PI / 4, Math.PI / 2, (Math.PI * 3) / 4, Math.PI, (Math.PI * 5) / 4, (Math.PI * 3) / 2, (Math.PI * 7) / 4]

  for (const entry of nodes) {
    const radius = entry.radius + CLUSTER_PADDING
    for (const angle of angles) {
      points.push({
        x: entry.x + Math.cos(angle) * radius,
        y: entry.y + Math.sin(angle) * radius,
      })
    }
  }

  return points
}

function makeCluster(id: string, nodes: FieldNode[]): KnowledgeCluster | null {
  if (!nodes.length) return null
  const hull = convexHull(expandedClusterPoints(nodes))
  const path = smoothClosedPath(hull)
  if (!path) return null
  const averageDepth = nodes.reduce((total, entry) => total + entry.node.depth_score, 0) / nodes.length
  return { id, path, opacity: clusterOpacity(averageDepth) }
}

function buildKnowledgeClusters(fieldNodes: FieldNode[]) {
  const visibleNodes = fieldNodes.filter((entry) => entry.node.is_visible)
  const byId = new Map(fieldNodes.map((entry) => [entry.node.node_id, entry]))
  const layerOneNodes = visibleNodes.filter((entry) => entry.node.layer === '1')
  const clusters: KnowledgeCluster[] = []

  const centerNode = visibleNodes.find((entry) => entry.node.layer === '0')
  if (centerNode) {
    const centerCluster = makeCluster('center-field', [centerNode, ...layerOneNodes])
    if (centerCluster) clusters.push(centerCluster)
  }

  for (const parent of layerOneNodes) {
    const children = fieldNodes.filter((entry) => entry.node.parent_id === parent.node.node_id && entry.node.is_visible)
    const cluster = makeCluster(`cluster-${parent.node.node_id}`, [parent, ...children])
    if (cluster) clusters.push(cluster)
  }

  if (!clusters.length && visibleNodes.length) {
    const fallbackCluster = makeCluster('visible-field', visibleNodes.filter((entry) => byId.has(entry.node.node_id)))
    if (fallbackCluster) clusters.push(fallbackCluster)
  }

  return clusters
}

function edgeDashArray(relationType: string) {
  if (relationType === 'leads-to') return '4 3'
  if (relationType === 'is-related-to') return '1.5 3'
  return undefined
}

function edgePath(edge: EdgeState, fieldNodeMap: Map<string, FieldNode>) {
  const source = fieldNodeMap.get(edge.source_node_id)
  const target = fieldNodeMap.get(edge.target_node_id)
  if (!source || !target) return null
  const dx = target.x - source.x
  const dy = target.y - source.y
  const distance = Math.max(1, Math.hypot(dx, dy))
  const curve = Math.min(28, distance * 0.09)
  const controlX = (source.x + target.x) / 2 - (dy / distance) * curve
  const controlY = (source.y + target.y) / 2 + (dx / distance) * curve
  return `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`
}

export default function GraphViewer({ onNodeClick, onNodeHover }: GraphViewerProps) {
  const { state } = useGraph()
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoveredNode, setHoveredNode] = useState<HoveredNode | null>(null)
  const [viewport, setViewport] = useState({ width: 1, height: 1 })
  const [viewportTransform, setViewportTransform] = useState<ViewportTransform>(DEFAULT_VIEWPORT_TRANSFORM)
  const [isPanning, setIsPanning] = useState(false)
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null)
  const hoveredNodeIdRef = useRef<string | null>(null)
  const hoverStartRef = useRef<{ nodeId: string; startedAt: number; logged: boolean } | null>(null)
  const hoverTimerRef = useRef<number | null>(null)
  const fieldDragRef = useRef<FieldDragState>({
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
    moved: false,
  })
  const suppressNodeClickRef = useRef(false)

  const fieldNodes = useMemo(
    () =>
      buildFieldNodes(
        state.nodes,
        Math.max(1, viewport.width),
        Math.max(1, viewport.height),
        state.selectedNodeId,
        state.recentUpdateNodeIds,
      ),
    [state.nodes, state.recentUpdateNodeIds, state.selectedNodeId, viewport.height, viewport.width],
  )

  const fieldNodeMap = useMemo(() => new Map(fieldNodes.map((entry) => [entry.node.node_id, entry])), [fieldNodes])
  const knowledgeClusters = useMemo(() => buildKnowledgeClusters(fieldNodes), [fieldNodes])
  const blindspotNodeIds = useMemo(() => new Set(state.blindspots.map((blindspot) => blindspot.node_id)), [state.blindspots])
  const labelNodes = useMemo(() => fieldNodes.filter((entry) => entry.node.is_visible), [fieldNodes])
  const fieldTransformStyle = useMemo<CSSProperties>(
    () => ({
      transform: `translate3d(${viewportTransform.x}px, ${viewportTransform.y}px, 0) scale(${viewportTransform.scale})`,
      transformOrigin: '0 0',
    }),
    [viewportTransform.scale, viewportTransform.x, viewportTransform.y],
  )

  const cancelHoverLogTimer = useCallback(() => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current)
      hoverTimerRef.current = null
    }
  }, [])

  const scheduleHoverLog = useCallback(
    (nodeId: string) => {
      const current = hoverStartRef.current
      if (current?.nodeId === nodeId) return

      cancelHoverLogTimer()
      const startedAt = window.performance.now()
      hoverStartRef.current = { nodeId, startedAt, logged: false }
      hoverTimerRef.current = window.setTimeout(() => {
        const hover = hoverStartRef.current
        if (!hover || hover.nodeId !== nodeId || hover.logged) return
        hover.logged = true
        onNodeHover?.(nodeId, Math.round(window.performance.now() - hover.startedAt))
      }, 1000)
    },
    [cancelHoverLogTimer, onNodeHover],
  )

  const setHoverCard = useCallback((node: NodeState, x: number, y: number) => {
    scheduleHoverLog(node.node_id)
    setHoveredNode((current) => ({
      nodeId: node.node_id,
      name: node.name,
      shortDefinition: current?.nodeId === node.node_id ? current.shortDefinition : node.short_definition ?? '',
      summary: current?.nodeId === node.node_id ? current.summary : undefined,
      x,
      y,
    }))

    if (hoveredNodeIdRef.current === node.node_id || node.state === 'unlit') {
      hoveredNodeIdRef.current = node.node_id
      return
    }

    hoveredNodeIdRef.current = node.node_id
    getNodeSummary(state.sessionId, node.node_id)
      .then((response) => {
        setHoveredNode((current) =>
          current?.nodeId === node.node_id
            ? { ...current, summary: response.summary, shortDefinition: response.short_definition }
            : current,
        )
      })
      .catch(() => {})
  }, [scheduleHoverLog, state.sessionId])

  const clearHoverCard = useCallback(() => {
    cancelHoverLogTimer()
    hoverStartRef.current = null
    hoveredNodeIdRef.current = null
    setHoveredNode(null)
  }, [cancelHoverLogTimer])

  const resetViewport = useCallback(() => {
    setViewportTransform(DEFAULT_VIEWPORT_TRANSFORM)
  }, [])

  const handleFieldMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (event.button !== 0) return
      fieldDragRef.current = {
        active: true,
        startX: event.clientX,
        startY: event.clientY,
        originX: viewportTransform.x,
        originY: viewportTransform.y,
        moved: false,
      }
      suppressNodeClickRef.current = false
      setIsPanning(true)
    },
    [viewportTransform.x, viewportTransform.y],
  )

  const handleFieldMouseMove = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    const drag = fieldDragRef.current
    if (!drag.active) return
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    if (Math.hypot(dx, dy) > PAN_CLICK_THRESHOLD) {
      drag.moved = true
    }
    setViewportTransform((current) => ({
      ...current,
      x: drag.originX + dx,
      y: drag.originY + dy,
    }))
  }, [])

  const finishFieldPan = useCallback(() => {
    const drag = fieldDragRef.current
    if (!drag.active) return
    fieldDragRef.current = { ...drag, active: false }
    setIsPanning(false)
    if (drag.moved) {
      suppressNodeClickRef.current = true
      window.setTimeout(() => {
        suppressNodeClickRef.current = false
      }, 0)
    }
  }, [])

  const handleFieldWheel = useCallback((event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const pointerX = event.clientX - rect.left
    const pointerY = event.clientY - rect.top

    setViewportTransform((current) => {
      const nextScale = clamp(current.scale * Math.exp(-event.deltaY * 0.001), MIN_FIELD_SCALE, MAX_FIELD_SCALE)
      const ratio = nextScale / current.scale
      return {
        scale: nextScale,
        x: pointerX - (pointerX - current.x) * ratio,
        y: pointerY - (pointerY - current.y) * ratio,
      }
    })
  }, [])

  const handleNodeClick = useCallback(
    (nodeId: string) => {
      if (suppressNodeClickRef.current) return
      onNodeClick?.(nodeId)
    },
    [onNodeClick],
  )

  useEffect(() => {
    if (!containerRef.current) return

    const resize = () => {
      if (!containerRef.current) return
      setViewport({
        width: Math.max(1, containerRef.current.clientWidth),
        height: Math.max(1, containerRef.current.clientHeight),
      })
    }

    const resizeObserver = new ResizeObserver(() => resize())
    resizeObserver.observe(containerRef.current)
    window.addEventListener('resize', resize)
    resize()

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', resize)
    }
  }, [])

  useEffect(() => () => cancelHoverLogTimer(), [cancelHoverLogTimer])

  return (
    <div
      ref={containerRef}
      className={`relative h-full w-full overflow-hidden rounded-b-[2.5rem] rounded-t-[1.75rem] ${
        isPanning ? 'cursor-grabbing' : 'cursor-grab'
      }`}
      style={{ background: GRAPH_COLORS.canvas }}
      onMouseDown={handleFieldMouseDown}
      onMouseMove={handleFieldMouseMove}
      onMouseUp={finishFieldPan}
      onMouseLeave={() => {
        finishFieldPan()
        clearHoverCard()
      }}
      onWheel={handleFieldWheel}
    >
      <button
        type="button"
        data-graph-control="reset"
        className="absolute right-4 top-4 z-30 rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-normal text-[#444441] backdrop-blur transition hover:border-[#B5D4F4] hover:text-[#185FA5]"
        onMouseDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation()
          resetViewport()
        }}
      >
        复位视角
      </button>

      <div className="absolute inset-0 will-change-transform" style={fieldTransformStyle}>
        <svg
          className="absolute inset-0 h-full w-full"
          viewBox={`0 0 ${viewport.width} ${viewport.height}`}
          role="img"
          aria-label="认知图谱"
        >
          <g className="pointer-events-none">
            {knowledgeClusters.map((cluster) => (
              <path key={cluster.id} d={cluster.path} fill={GRAPH_COLORS.cluster} opacity={cluster.opacity} stroke="none" />
            ))}
          </g>

          <g>
            {state.edges.map((edge) => {
              const path = edgePath(edge, fieldNodeMap)
              if (!path) return null
              const isHovered = hoveredEdgeId === edge.edge_id
              return (
                <path
                  key={edge.edge_id}
                  d={path}
                  fill="none"
                  stroke={GRAPH_COLORS.edge}
                  strokeWidth={isHovered ? 1.5 : 0.8}
                  strokeOpacity={isHovered ? 0.55 : 0.4}
                  strokeLinecap="round"
                  strokeDasharray={edgeDashArray(edge.relation_type)}
                  className="transition-[stroke-width,stroke-opacity] duration-150"
                  pointerEvents="stroke"
                  onMouseEnter={() => setHoveredEdgeId(edge.edge_id)}
                  onMouseLeave={() => setHoveredEdgeId(null)}
                />
              )
            })}
          </g>

          <g>
            {fieldNodes.map((entry) => {
              const isSelected = entry.node.node_id === state.selectedNodeId
              const isBlindspot = blindspotNodeIds.has(entry.node.node_id)
              const isRecent = state.recentUpdateNodeIds.includes(entry.node.node_id)
              return (
                <g
                  key={entry.node.node_id}
                  role="button"
                  tabIndex={0}
                  aria-label={`聚焦概念 ${entry.node.name}`}
                  aria-pressed={isSelected}
                  className="cursor-pointer outline-none"
                  onClick={() => handleNodeClick(entry.node.node_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      handleNodeClick(entry.node.node_id)
                    }
                  }}
                  onMouseEnter={(event) => {
                    const rect = containerRef.current?.getBoundingClientRect()
                    if (!rect) return
                    setHoverCard(entry.node, event.clientX - rect.left, event.clientY - rect.top)
                  }}
                  onMouseMove={(event) => {
                    const rect = containerRef.current?.getBoundingClientRect()
                    if (!rect) return
                    setHoverCard(entry.node, event.clientX - rect.left, event.clientY - rect.top)
                  }}
                  onMouseLeave={clearHoverCard}
                >
                  {isSelected && (
                    <circle
                      cx={entry.x}
                      cy={entry.y}
                      r={entry.radius + 5}
                      fill="none"
                      stroke={GRAPH_COLORS.nodeStroke}
                      strokeWidth={1.2}
                      strokeOpacity={0.55}
                    />
                  )}
                  {isRecent && (
                    <circle
                      cx={entry.x}
                      cy={entry.y}
                      r={entry.radius + 8}
                      fill="none"
                      stroke={GRAPH_COLORS.node}
                      strokeWidth={0.8}
                      strokeOpacity={0.35}
                      className="animate-ping"
                    />
                  )}
                  {isBlindspot && entry.node.state === 'unlit' && (
                    <circle
                      cx={entry.x}
                      cy={entry.y}
                      r={entry.radius + 4}
                      fill="none"
                      stroke={GRAPH_COLORS.nodeStroke}
                      strokeWidth={0.7}
                      strokeDasharray="2 3"
                      strokeOpacity={0.42}
                    />
                  )}
                  <circle
                    cx={entry.x}
                    cy={entry.y}
                    r={entry.radius}
                    fill={GRAPH_COLORS.node}
                    fillOpacity={conceptNodeOpacity(entry.node)}
                    stroke={GRAPH_COLORS.nodeStroke}
                    strokeWidth={0.5}
                  />
                </g>
              )
            })}
          </g>

          <g className="pointer-events-none">
            {labelNodes.map((entry) => {
              const isSelected = entry.node.node_id === state.selectedNodeId
              const labelOpacity = isSelected ? 0.98 : entry.node.state === 'explored' ? 0.9 : entry.node.state === 'activated' ? 0.78 : 0.64
              return (
                <text
                  key={`label-${entry.node.node_id}`}
                  x={entry.x}
                  y={entry.y + entry.radius + 8}
                  textAnchor="middle"
                  dominantBaseline="hanging"
                  fill={GRAPH_COLORS.label}
                  fillOpacity={labelOpacity}
                  fontSize={conceptLabelSize(entry.node)}
                  fontWeight={400}
                  style={{ userSelect: 'none' }}
                >
                  {entry.node.name}
                </text>
              )
            })}
          </g>
        </svg>
      </div>

      {hoveredNode && (
        <div
          className="pointer-events-none absolute z-20 max-w-xs rounded-xl border border-slate-200 bg-white/90 px-3 py-2 backdrop-blur"
          style={{ left: hoveredNode.x + 16, top: hoveredNode.y + 12 }}
        >
          <div className="text-sm font-normal text-[#3d3d3a]">{hoveredNode.name}</div>
          {hoveredNode.shortDefinition && <div className="mt-1 text-xs leading-relaxed text-slate-600">{hoveredNode.shortDefinition}</div>}
          {hoveredNode.summary && <div className="mt-2 border-t border-slate-200 pt-2 text-xs leading-relaxed text-slate-500">{hoveredNode.summary}</div>}
        </div>
      )}
    </div>
  )
}
