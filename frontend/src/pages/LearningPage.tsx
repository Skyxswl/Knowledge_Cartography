import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import { getNodeQuestions, getNodeTrace, getSession, logExperimentEvent } from '@/api/sessions'
import { createTurn, listTurns } from '@/api/turns'
import type { QuestionCategory, SuggestedQuestion } from '@/api/types'
import type { ChatMessage } from '@/components/chat/types'
import ChatHistory from '@/components/chat/ChatHistory'
import ChatInput, { type ChatInputHandle } from '@/components/chat/ChatInput'
import GraphViewer from '@/components/graph/GraphViewer'
import NodeInteractionPanel from '@/components/interaction/NodeInteractionPanel'
import ErrorBoundary from '@/components/ErrorBoundary'
import { GraphProvider, useGraph } from '@/store/GraphContext'

const PANEL_STATE_PREFIX = 'zoommind:panel-state:'

interface PersistedPanelState {
  selectedNodeId: string | null
  suggestedQuestions: Array<{ node_id: string; category: QuestionCategory; prompt: string }>
  traceTurns: Array<{ turn_id: string; speaker: string; content: string; timestamp: string }>
  activeTurnId: string | null
}

function getPanelStorageKey(sessionId: string) {
  return `${PANEL_STATE_PREFIX}${sessionId}`
}

function getPreferredTraceTurnId(
  turns: Array<{ turn_id: string; speaker: string }>,
  fallbackTurnId?: string | null,
) {
  const assistantTurn = turns.find((turn) => turn.speaker === 'assistant')
  if (assistantTurn) return assistantTurn.turn_id
  return turns[0]?.turn_id ?? fallbackTurnId ?? null
}

function getSendErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) {
    return '发送失败，请稍后重试。'
  }
  if (error.code === 'ECONNABORTED') {
    return '模型响应超时，请稍后重试或换一个更短的问题。'
  }
  if (error.response) {
    const detail = error.response.data?.detail
    return detail ? `后端返回错误：${detail}` : `后端返回错误：HTTP ${error.response.status}`
  }
  return '无法连接后端，请确认 http://127.0.0.1:8000 正在运行。'
}

function LearningPageInner() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const { state, dispatch } = useGraph()
  const chatInputRef = useRef<ChatInputHandle>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [graphLoaded, setGraphLoaded] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [pendingQuestionPrompt, setPendingQuestionPrompt] = useState<string | null>(null)
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function recordGraphEvent(
    eventType: string,
    payload: {
      nodeId?: string | null
      turnId?: string | null
      questionCategory?: QuestionCategory | null
      durationMs?: number | null
      metadata?: Record<string, unknown>
    } = {},
  ) {
    if (!sessionId) return
    void logExperimentEvent(sessionId, {
      event_type: eventType,
      node_id: payload.nodeId ?? null,
      turn_id: payload.turnId ?? null,
      question_category: payload.questionCategory ?? null,
      duration_ms: payload.durationMs ?? null,
      metadata: payload.metadata ?? {},
    }).catch(() => {})
  }

  useEffect(() => {
    if (!sessionId) return
    Promise.all([getSession(sessionId), listTurns(sessionId)])
      .then(([session, turns]) => {
        dispatch({ type: 'INIT_GRAPH', payload: session })
        setMessages(
          turns.map((turn) => ({
            turn_id: turn.turn_id,
            speaker: turn.speaker as 'user' | 'assistant',
            content: turn.content,
            timestamp: turn.timestamp,
          })),
        )
        if (typeof window !== 'undefined') {
          const raw = window.sessionStorage.getItem(getPanelStorageKey(sessionId))
          if (raw) {
            try {
              const persisted = JSON.parse(raw) as PersistedPanelState
              dispatch({
                type: 'RESTORE_PANEL_STATE',
                payload: {
                  selectedNodeId: persisted.selectedNodeId,
                  suggestedQuestions: persisted.suggestedQuestions ?? [],
                  traceTurns: persisted.traceTurns ?? [],
                },
              })
              setActiveTurnId(persisted.activeTurnId ?? null)
              if (persisted.selectedNodeId) {
                getNodeTrace(sessionId, persisted.selectedNodeId)
                  .then((trace) => {
                    dispatch({ type: 'SET_TRACE_TURNS', payload: trace.turns })
                    setActiveTurnId(getPreferredTraceTurnId(trace.turns, persisted.activeTurnId))
                  })
                  .catch(() => {})
              }
            } catch (error) {
              console.warn('Failed to restore panel state', error)
            }
          }
        }
        setGraphLoaded(true)
        setLoadError(null)
      })
      .catch((error) => {
        console.error('Failed to load learning page', error)
        setLoadError('学习页加载失败，请确认后端会话接口可用。')
      })
  }, [dispatch, sessionId])

  useEffect(() => {
    if (!sessionId || typeof window === 'undefined' || !graphLoaded) return
    const persisted: PersistedPanelState = {
      selectedNodeId: state.selectedNodeId,
      suggestedQuestions: state.suggestedQuestions,
      traceTurns: state.traceTurns,
      activeTurnId,
    }
    window.sessionStorage.setItem(getPanelStorageKey(sessionId), JSON.stringify(persisted))
  }, [
    activeTurnId,
    graphLoaded,
    sessionId,
    state.selectedNodeId,
    state.suggestedQuestions,
    state.traceTurns,
  ])

  async function handleSend(content: string) {
    if (!sessionId || isSending) return
    setIsSending(true)
    const optimisticUser: ChatMessage = {
      turn_id: `optimistic-${Date.now()}`,
      speaker: 'user',
      content,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticUser])

    try {
      const response = await createTurn(sessionId, content)
      dispatch({ type: 'APPLY_TURN', payload: response })
      setMessages((prev) => [
        ...prev,
        {
          turn_id: response.turn_id,
          speaker: 'assistant',
          content: response.ai_reply,
          timestamp: new Date().toISOString(),
        },
      ])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          turn_id: `error-${Date.now()}`,
          speaker: 'assistant',
          content: getSendErrorMessage(error),
          timestamp: new Date().toISOString(),
        },
      ])
    } finally {
      setIsSending(false)
      setPendingQuestionPrompt(null)
    }
  }

  async function handleNodeSelect(nodeId: string, source: 'graph' | 'blindspot' = 'graph') {
    if (!sessionId) return
    const blindspot = state.blindspots.find((item) => item.node_id === nodeId)
    if (source === 'blindspot') {
      recordGraphEvent('GI-B', {
        nodeId,
        metadata: {
          blindspot_type: blindspot?.blindspot_type ?? null,
          priority: blindspot?.priority ?? null,
        },
      })
    }
    dispatch({ type: 'SELECT_NODE', payload: nodeId })
    // NOTE: Clicking a node should NOT activate it - only user mentioning
    // the concept in chat should activate nodes. Click just shows details.
    try {
      const trace = await getNodeTrace(sessionId, nodeId)
      dispatch({ type: 'SET_TRACE_TURNS', payload: trace.turns })
      setActiveTurnId(getPreferredTraceTurnId(trace.turns))
    } catch {
      dispatch({ type: 'SET_TRACE_TURNS', payload: [] })
      setActiveTurnId(null)
    }
    try {
      const response = await getNodeQuestions(sessionId, nodeId)
      dispatch({ type: 'SET_SUGGESTED_QUESTIONS', payload: response.questions })
    } catch {
      // Keep the local fallback questions produced by SELECT_NODE.
    }
  }

  function handleQuestionFill(question: SuggestedQuestion) {
    if (isSending) return
    recordGraphEvent('GI-C', {
      nodeId: question.node_id,
      questionCategory: question.category,
      metadata: {
        action: 'fill',
        prompt: question.prompt,
      },
    })
    chatInputRef.current?.setValue(question.prompt)
  }

  function handleQuestionSend(question: SuggestedQuestion) {
    if (isSending) return
    recordGraphEvent('GI-C', {
      nodeId: question.node_id,
      questionCategory: question.category,
      metadata: {
        action: 'send',
        prompt: question.prompt,
      },
    })
    setPendingQuestionPrompt(question.prompt)
    void handleSend(question.prompt)
  }

  function handleTraceSelect(turnId: string) {
    setActiveTurnId(turnId)
    recordGraphEvent('GI-T', {
      nodeId: state.selectedNodeId,
      turnId,
    })
  }

  function handleNodeHover(nodeId: string, durationMs: number) {
    recordGraphEvent('GI-H', {
      nodeId,
      durationMs,
    })
  }

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-[#f7fbff] md:flex-row">
      <div className="flex h-[42%] min-h-[290px] flex-shrink-0 flex-col border-b border-slate-200 bg-white md:h-auto md:w-[40%] md:border-b-0 md:border-r">
        {!graphLoaded && !loadError && (
          <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
            正在加载学习会话…
          </div>
        )}
        {loadError && (
          <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            {loadError}
          </div>
        )}
        <ChatHistory messages={messages} activeTurnId={activeTurnId} />
        <ChatInput ref={chatInputRef} onSend={handleSend} disabled={!graphLoaded} busy={isSending} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_100%)] p-3 md:p-4">
        <div className="mb-2 px-1 md:mb-3 md:px-2">
          <div className="text-xs uppercase tracking-[0.22em] text-slate-400">Concept Field</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">认知图谱</div>
        </div>
        <div className="min-h-[200px] flex-[4] md:min-h-[190px]">
          <ErrorBoundary>
            <GraphViewer onNodeClick={(nodeId) => void handleNodeSelect(nodeId)} onNodeHover={handleNodeHover} />
          </ErrorBoundary>
        </div>
        <div className="mt-3 min-h-[300px] flex-[5] overflow-y-auto rounded-[1.75rem] border border-white/60 bg-white shadow-sm md:mt-4 md:min-h-[330px]">
          <NodeInteractionPanel
            activeTurnId={activeTurnId}
            isSending={isSending}
            pendingQuestionPrompt={pendingQuestionPrompt}
            onBlindspotSelect={(nodeId) => void handleNodeSelect(nodeId, 'blindspot')}
            onQuestionFill={handleQuestionFill}
            onQuestionSend={handleQuestionSend}
            onTraceSelect={handleTraceSelect}
          />
        </div>
      </div>
    </div>
  )
}

export default function LearningPage() {
  return (
    <GraphProvider>
      <LearningPageInner />
    </GraphProvider>
  )
}
