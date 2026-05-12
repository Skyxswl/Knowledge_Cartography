export interface ChatMessage {
  turn_id: string
  speaker: 'user' | 'assistant'
  content: string
  timestamp: string
}
