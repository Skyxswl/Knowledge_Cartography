import { apiClient } from './client'
import type {
  ExperimentEventItem,
  ExperimentEventPayload,
  ExpandResponse,
  GraphSnapshotItem,
  NodeSummaryResponse,
  NodeTraceResponse,
  QuestionsResponse,
  SessionResponse,
} from './types'

export async function createSession(topic: string): Promise<SessionResponse> {
  const { data } = await apiClient.post<SessionResponse>('/api/sessions', { topic })
  return data
}

export async function getSession(sessionId: string): Promise<SessionResponse> {
  const { data } = await apiClient.get<SessionResponse>(`/api/sessions/${sessionId}`)
  return data
}

export async function getNodeSummary(sessionId: string, nodeId: string): Promise<NodeSummaryResponse> {
  const { data } = await apiClient.get<NodeSummaryResponse>(`/api/sessions/${sessionId}/nodes/${nodeId}/summary`)
  return data
}

export async function getNodeTrace(sessionId: string, nodeId: string): Promise<NodeTraceResponse> {
  const { data } = await apiClient.get<NodeTraceResponse>(`/api/sessions/${sessionId}/nodes/${nodeId}/trace`)
  return data
}

export async function expandNode(sessionId: string, nodeId: string): Promise<ExpandResponse> {
  const { data } = await apiClient.patch<ExpandResponse>(`/api/sessions/${sessionId}/nodes/${nodeId}/expand`)
  return data
}

export async function getNodeQuestions(sessionId: string, nodeId: string): Promise<QuestionsResponse> {
  const { data } = await apiClient.post<QuestionsResponse>(`/api/sessions/${sessionId}/nodes/${nodeId}/questions`)
  return data
}

export async function logExperimentEvent(
  sessionId: string,
  payload: ExperimentEventPayload,
): Promise<ExperimentEventItem> {
  const { data } = await apiClient.post<ExperimentEventItem>(`/api/sessions/${sessionId}/events`, payload)
  return data
}

export async function createGraphSnapshot(sessionId: string, label?: string): Promise<GraphSnapshotItem> {
  const { data } = await apiClient.post<GraphSnapshotItem>(`/api/sessions/${sessionId}/snapshots`, {
    label: label ?? null,
  })
  return data
}
