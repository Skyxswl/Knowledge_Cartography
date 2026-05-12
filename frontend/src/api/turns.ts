import { apiClient } from './client'
import type { TurnItem, TurnResponse } from './types'

export async function createTurn(sessionId: string, content: string): Promise<TurnResponse> {
  const { data } = await apiClient.post<TurnResponse>(`/api/sessions/${sessionId}/turns`, {
    content,
    speaker: 'user',
  })
  return data
}

export async function listTurns(sessionId: string): Promise<TurnItem[]> {
  const { data } = await apiClient.get<TurnItem[]>(`/api/sessions/${sessionId}/turns`)
  return data
}
