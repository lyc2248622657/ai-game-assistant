import { useCallback, useEffect, useState } from 'react'
import { api, streamChat } from './api/client'
import { AgentTimeline } from './components/AgentTimeline'
import { ChatWindow } from './components/ChatWindow'
import { CitationCard } from './components/CitationCard'
import { EventCountdown } from './components/EventCountdown'
import { SessionBar } from './components/SessionBar'
import type { AgentEvent, ChatMessage, Citation, SessionInfo, UsageInfo } from './types'

/** 多游戏统一对话框：不再按游戏切换模块，由 Agent 自动判别游戏（原神/明日方舟） */
export default function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [currentSession, setCurrentSession] = useState<SessionInfo | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [loading, setLoading] = useState(false)

  // 初始化：加载会话列表并自动进入最近一个对话（避免每次打开新建空对话）
  useEffect(() => {
    api.listSessions().then((list) => {
      setSessions(list)
      if (list.length > 0) {
        setCurrentSession(list[0])
        api.getMessages(list[0].session_id).then(({ messages }) =>
          setMessages(
            messages.map((m) => ({
              role: m.role as 'user' | 'assistant',
              content: m.content,
            })),
          ),
        )
      }
    })
  }, [])

  /** 新建对话：立即创建并切换过去（与上次对话隔离） */
  const handleCreate = useCallback(() => {
    api.createSession('genshin', `新对话 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`).then((s) => {
      setCurrentSession(s)
      setMessages([])
      setEvents([])
      api.listSessions().then(setSessions)
    })
  }, [])

  /** 删除对话：删除当前选中的会话（含历史消息） */
  const handleDelete = useCallback(
    (s: SessionInfo) => {
      api.deleteSession(s.session_id).then(() => {
        api.listSessions().then((list) => {
          setSessions(list)
          if (s.session_id === currentSession?.session_id) {
            // 删除的是当前会话 → 自动切到最近会话（或清空）
            const next = list[0] ?? null
            setCurrentSession(next)
            setMessages([])
            setEvents([])
            if (next) {
              api.getMessages(next.session_id).then(({ messages }) =>
                setMessages(
                  messages.map((m) => ({
                    role: m.role as 'user' | 'assistant',
                    content: m.content,
                  })),
                ),
              )
            }
          }
        })
      })
    },
    [currentSession],
  )

  const handleSend = useCallback(
    async (text: string) => {
      if (loading) return
      setLoading(true)
      setMessages((m) => [...m, { role: 'user', content: text }])
      setEvents([])

      try {
        await streamChat(
          null,
          text,
          currentSession?.session_id ?? null, // 已有会话 → 在老窗口续聊；无会话 → 后端新建
          (ev) => {
            setEvents((prev) => [...prev, ev])
            const patch = (fn: (last: ChatMessage) => ChatMessage) => {
              setMessages((m) => {
                const last = m[m.length - 1]
                if (last?.role === 'assistant') return [...m.slice(0, -1), fn(last)]
                return m
              })
            }
            if (ev.type === 'answer' && ev.delta) {
              // 流式模式为增量追加；当前非流式为整段覆盖
              patch((last) => ({ ...last, content: ev.delta! }))
            }
            if (ev.type === 'citations' && ev.citations) {
              patch((last) => ({ ...last, citations: ev.citations as Citation[] }))
            }
            if (ev.type === 'usage' && ev.usage) {
              patch((last) => ({ ...last, usage: ev.usage as UsageInfo }))
            }
            if (ev.type === 'suggestions' && ev.suggestions) {
              patch((last) => ({ ...last, suggestions: ev.suggestions as string[] }))
            }
            if (ev.type === 'image' && ev.image_url) {
              patch((last) => ({ ...last, image_url: ev.image_url }))
            }
            if (ev.type === 'related_entities' && ev.related_entities) {
              patch((last) => ({ ...last, related_entities: ev.related_entities as string[] }))
            }
            if (ev.type === 'guides' && ev.guides) {
              patch((last) => ({ ...last, guides: ev.guides }))
            }
            if (ev.type === 'session' && ev.session_id && !currentSession) {
              setCurrentSession({ session_id: ev.session_id } as SessionInfo)
            }
          },
        )
      } catch (e) {
        setMessages((m) => [...m, { role: 'assistant', content: `错误：${(e as Error).message}` }])
      } finally {
        setLoading(false)
        api.listSessions().then(setSessions)
      }
    },
    [currentSession, loading],
  )

  return (
    <div className="flex h-full">
      <SessionBar
        sessions={sessions}
        current={currentSession}
        onSelect={(s) => {
          setCurrentSession(s)
          setEvents([])
          api.getMessages(s.session_id).then(({ messages }) =>
            setMessages(
              messages.map((m) => ({
                role: m.role as 'user' | 'assistant',
                content: m.content,
              })),
            ),
          )
        }}
        onCreate={handleCreate}
        onDelete={handleDelete}
      />
      <div className="flex flex-1 flex-col">
        <header className="border-b px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold text-gray-800">多游戏智能助手</h1>
              <p className="text-xs text-gray-500">原神 · 明日方舟 统一问答 · 由 Agent 自动识别游戏并从对应官方数据源获取</p>
            </div>
            <div className="flex gap-2">
              <span className="rounded-full bg-green-50 px-3 py-1 text-xs text-green-600">原神 → 原神wiki</span>
              <span className="rounded-full bg-amber-50 px-3 py-1 text-xs text-amber-600">明日方舟 → PRTS</span>
            </div>
          </div>
        </header>
        <main className="flex flex-1 gap-4 overflow-hidden p-4">
          <ChatWindow
            messages={messages}
            loading={loading}
            gameId={currentSession?.game_id ?? null}
            onSend={handleSend}
          />
          <div className="flex w-80 flex-col gap-3 overflow-y-auto">
            <EventCountdown />
            <AgentTimeline events={events} />
            <CitationCard
              citations={messages[messages.length - 1]?.citations ?? []}
            />
          </div>
        </main>
      </div>
    </div>
  )
}
