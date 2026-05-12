import { useEffect, useRef } from 'react'
import SimpleMarkdown from '@/components/common/SimpleMarkdown'
import type { ChatMessage } from './types'

interface ChatHistoryProps {
  messages: ChatMessage[]
  activeTurnId?: string | null
}

export default function ChatHistory({ messages, activeTurnId }: ChatHistoryProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (activeTurnId && activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [activeTurnId])

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-4">
      {messages.map((msg) => {
        const isUser = msg.speaker === 'user'
        const isActive = activeTurnId === msg.turn_id
        return (
          <div
            key={msg.turn_id}
            ref={isActive ? activeRef : null}
            className={`mb-3 flex ${isUser ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[82%] rounded-2xl px-4 py-2 text-sm leading-relaxed transition-all ${
                isUser
                  ? 'rounded-br-sm bg-slate-900 text-white'
                  : 'rounded-bl-sm bg-slate-100 text-slate-800'
              } ${isActive ? 'ring-2 ring-cyan-400 ring-offset-2' : ''}`}
            >
              {isUser ? (
                msg.content
              ) : (
                <SimpleMarkdown
                  content={msg.content}
                  className="[&_h1]:text-slate-900 [&_h2]:text-slate-900 [&_h3]:text-slate-900 [&_p]:text-inherit [&_strong]:text-inherit [&_ul]:text-inherit [&_ol]:text-inherit"
                />
              )}
            </div>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
