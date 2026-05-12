import { useState, useEffect, forwardRef, useImperativeHandle } from 'react'
import { Button } from '@/components/ui/button'

export interface ChatInputHandle {
  setValue: (v: string) => void
}

interface ChatInputProps {
  onSend: (content: string) => void
  disabled?: boolean
  busy?: boolean
  fillContent?: string | null
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  ({ onSend, disabled, busy, fillContent }, ref) => {
    const [value, setValue] = useState('')

    useImperativeHandle(ref, () => ({ setValue }))

    useEffect(() => {
      if (fillContent) setValue(fillContent)
    }, [fillContent])

    function handleSend() {
      const text = value.trim()
      if (!text || disabled) return
      onSend(text)
      setValue('')
    }

    return (
      <div className="flex items-center gap-2 border-t border-gray-200 bg-white p-3">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder={busy ? '模型正在回答…' : disabled ? '等待连接…' : '输入你的问题，按 Enter 发送'}
          disabled={disabled || busy}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500 disabled:opacity-50"
        />
        <Button onClick={handleSend} disabled={disabled || busy || !value.trim()} size="sm">
          {busy ? '发送中…' : '发送'}
        </Button>
      </div>
    )
  }
)

ChatInput.displayName = 'ChatInput'
export default ChatInput
