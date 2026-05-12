import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { createSession } from '@/api/sessions'

const STORAGE_KEY = 'zoommind_recent_topics'
const MAX_RECENT = 3

function loadRecentTopics(): string[] {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveRecentTopic(topic: string) {
  const existing = loadRecentTopics()
  const updated = [topic, ...existing.filter((t) => t !== topic)].slice(0, MAX_RECENT)
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
}

export default function TopicInputPage() {
  const [topic, setTopic] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [recentTopics, setRecentTopics] = useState<string[]>([])
  const navigate = useNavigate()

  useEffect(() => {
    setRecentTopics(loadRecentTopics())
  }, [])

  async function handleSubmit() {
    if (!topic.trim()) {
      setError('请输入知识主题，不能为空')
      return
    }
    setError('')
    setLoading(true)
    try {
      const session = await createSession(topic.trim())
      saveRecentTopic(topic.trim())
      navigate(`/learn/${session.session_id}`)
    } catch {
      setError('创建学习会话失败，请检查后端是否运行')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-full flex-col items-center justify-center bg-white px-4">
      {/* Guiding text */}
      <p className="mb-6 text-base text-gray-500">
        输入你想学习的知识主题
      </p>

      {/* Topic input */}
      <input
        type="text"
        value={topic}
        onChange={(e) => {
          setTopic(e.target.value)
          if (error) setError('')
        }}
        onKeyDown={(e) => e.key === 'Enter' && !loading && handleSubmit()}
        placeholder="例如：细胞生物学、机器学习入门、中国近代史…"
        disabled={loading}
        className="mb-2 w-full max-w-lg rounded-lg border border-gray-300 px-4 py-3 text-sm outline-none focus:border-gray-500 disabled:opacity-50"
      />

      {/* Inline validation error */}
      {error && (
        <p className="mb-3 w-full max-w-lg text-xs text-red-500">{error}</p>
      )}

      {/* Submit button */}
      <Button
        onClick={handleSubmit}
        disabled={loading}
        className="w-full max-w-lg"
      >
        {loading ? '创建中…' : '开始学习'}
      </Button>

      {/* Recent topics */}
      {recentTopics.length > 0 && (
        <div className="mt-8 w-full max-w-lg">
          <p className="mb-2 text-xs text-gray-400">最近学习过：</p>
          <div className="flex flex-wrap gap-2">
            {recentTopics.map((t) => (
              <button
                key={t}
                onClick={() => setTopic(t)}
                className="rounded-full border border-gray-300 px-3 py-1 text-xs text-gray-600 transition-colors hover:border-gray-500 hover:text-gray-900"
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
