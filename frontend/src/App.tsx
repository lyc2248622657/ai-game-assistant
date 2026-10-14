import { useCallback, useEffect, useRef, useState } from 'react'
import { api, streamChat, StreamInterruptedError } from './api/client'
import { AdminPanel } from './components/AdminPanel'
import { AgentTimeline } from './components/AgentTimeline'
import { ChatWindow } from './components/ChatWindow'
import { CitationCard } from './components/CitationCard'
import ErrorBoundary from './components/ErrorBoundary'
import { EventCountdown } from './components/EventCountdown'
import { SessionBar } from './components/SessionBar'
import { SettingsModal } from './components/SettingsModal'
import type { AgentEvent, ChatMessage, Citation, SessionInfo, UsageInfo } from './types'

/** 多游戏统一对话框：不再按游戏切换模块，由 Agent 自动判别游戏（原神/明日方舟）
 *  顶部 tab：对话 / 管理控制台（知识库运维 + 检索测试，方向①）
 */
export default function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  )
}

function AppContent() {
  const [tab, setTab] = useState<'chat' | 'admin'>('chat')
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [currentSession, setCurrentSession] = useState<SessionInfo | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [keyConfigured, setKeyConfigured] = useState(false)
  // 方向③：AbortController 控制面 —— 停止生成 = 中断 SSE 流（后端 is_disconnected 检测到断连即停止）
  const abortRef = useRef<AbortController | null>(null)

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
              images: (m as { images?: string[] }).images?.length ? (m as { images?: string[] }).images : undefined,
            })),
          ),
        )
      }
    })
    api.getKeyStatus().then((s) => setKeyConfigured(s.configured))
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
                    images: (m as { images?: string[] }).images?.length ? (m as { images?: string[] }).images : undefined,
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
    async (text: string, imagePath?: string, imageUrl?: string) => {
      if (loading) return
      setLoading(true)
      // 每次发送创建独立控制面，支持中途停止
      const controller = new AbortController()
      abortRef.current = controller
      setMessages((m) => [
        ...m,
        { role: 'user', content: text, image_path: imagePath, user_image: imageUrl },
        { role: 'assistant', content: '' },
      ])
      setEvents([])

      try {
        await streamChat(
          null,
          text,
          currentSession?.session_id ?? null, // 已有会话 → 在老窗口续聊；无会话 → 后端新建
          imagePath ?? null,
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
            if (ev.type === 'image' && (ev.image_url || ev.images?.length)) {
              patch((last) => ({
                ...last,
                image_url: ev.image_url || ev.images?.[0],
                images: ev.images?.length ? (ev.images as string[]) : ev.image_url ? [ev.image_url] : undefined,
              }))
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
          controller.signal, // 方向③：可中断的 SSE 控制面
        )
      } catch (e) {
        // AbortError = 用户主动停止：不当作错误提示
        if ((e as Error).name === 'AbortError') return
        // 已收到部分内容后断流：连接层已自动重试过，此处提示用户，不自动重发（避免重复生成）
        const msg =
          e instanceof StreamInterruptedError
            ? '连接中断（已收到部分回答）。请重新发送以继续。'
            : `错误：${(e as Error).message}`
        setMessages((m) => {
          const last = m[m.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            return [...m.slice(0, -1), { role: 'assistant', content: msg }]
          }
          return [...m, { role: 'assistant', content: msg }]
        })
      } finally {
        abortRef.current = null
        setLoading(false)
        api.listSessions().then(setSessions)
      }
    },
    [currentSession, loading],
  )

  /** 方向③：停止当前生成（中断 SSE 流，后端断连检测自动停止拉取后续节点） */
  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

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
                images: (m as { images?: string[] }).images?.length ? (m as { images?: string[] }).images : undefined,
              })),
            ),
          )
        }}
        onCreate={handleCreate}
        onDelete={handleDelete}
      />
      <div className="flex flex-1 flex-col">
        <header className="glass-header sticky top-0 z-10 px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="gradient-text text-lg font-bold">多游戏智能助手</h1>
              <p className="text-xs text-gray-500">原神 · 明日方舟 统一问答 · 由 Agent 自动识别游戏并从对应官方数据源获取</p>
            </div>
            <div className="flex gap-2">
              <div className="mr-2 flex items-center gap-1 rounded-full border border-gray-200 bg-white/80 p-0.5 shadow-sm">
                <button
                  onClick={() => setTab('chat')}
                  className={`rounded-full px-3 py-1 text-xs transition ${
                    tab === 'chat' ? 'btn-brand font-medium' : 'text-gray-500 hover:bg-gray-50'
                  }`}
                >
                  对话
                </button>
                <button
                  onClick={() => setTab('admin')}
                  className={`rounded-full px-3 py-1 text-xs transition ${
                    tab === 'admin' ? 'btn-brand font-medium' : 'text-gray-500 hover:bg-gray-50'
                  }`}
                >
                  管理控制台
                </button>
              </div>
              <span className="rounded-full bg-green-50 px-3 py-1 text-xs text-green-600">原神 → 原神wiki</span>
              <span className="rounded-full bg-amber-50 px-3 py-1 text-xs text-amber-600">明日方舟 → PRTS</span>
              <button
                onClick={() => setSettingsOpen(true)}
                className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white/80 px-3 py-1 text-xs text-gray-600 shadow-sm transition hover:bg-gray-50"
                title="模型设置（API Key）"
              >
                <span className={keyConfigured ? 'text-green-500' : 'text-amber-500'}>●</span>
                ⚙ 设置
              </button>
            </div>
          </div>
        </header>
        {tab === 'admin' ? (
          <AdminPanel />
        ) : (
          <main className="flex flex-1 gap-4 overflow-hidden p-4">
            <ChatWindow
              messages={messages}
              loading={loading}
              gameId={currentSession?.game_id ?? null}
              onSend={handleSend}
              onStop={handleStop}
            />
            <div className="flex w-80 flex-col gap-3 overflow-y-auto">
              <EventCountdown />
              <AgentTimeline events={events} />
              <CitationCard citations={messages[messages.length - 1]?.citations ?? []} />
            </div>
          </main>
        )}
      </div>
      <SettingsModal
        open={settingsOpen}
        onClose={() => {
          setSettingsOpen(false)
          api.getKeyStatus().then((s) => setKeyConfigured(s.configured))
        }}
      />
    </div>
  )
}
