import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, setToken, streamChat, StreamInterruptedError, AuthRequiredError } from './api/client'
import { AdminPanel } from './components/AdminPanel'
import { AgentTimeline } from './components/AgentTimeline'
import { ChatWindow } from './components/ChatWindow'
import { CitationCard } from './components/CitationCard'
import ErrorBoundary from './components/ErrorBoundary'
import { EventCountdown } from './components/EventCountdown'
import { SessionBar } from './components/SessionBar'
import { SettingsModal } from './components/SettingsModal'
import type { AgentEvent, ChatMessage, SessionInfo, UsageInfo } from './types'
import { mapHistory, normalizeCitations } from './utils/history'
import { describeError } from './utils/errors'

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
  // 接口鉴权：本机回环免令牌；外部部署时后端返回 401，这里弹出令牌输入
  const [authState, setAuthState] = useState<'checking' | 'ok' | 'required'>('checking')
  const [authMessage, setAuthMessage] = useState('')
  // 方向③：AbortController 控制面 —— 停止生成 = 中断 SSE 流（后端 is_disconnected 检测到断连即停止）
  const abortRef = useRef<AbortController | null>(null)
  // 历史读取序号：快速切会话时，只有"最后一次"请求的响应允许写 messages
  const historySeq = useRef(0)

  /** 加载某个会话的历史消息：带序号守卫，防止 A→B→C 连点时 B 的迟到响应覆盖 C */
  const loadHistory = useCallback((sessionId: string) => {
    const seq = ++historySeq.current
    api
      .getMessages(sessionId)
      .then(({ messages }) => {
        if (seq === historySeq.current) setMessages(mapHistory(messages))
      })
      .catch(() => {
        if (seq === historySeq.current) setMessages([])
      })
  }, [])

  // 鉴权探测：/api/auth/status 豁免鉴权；回环来源会回传明文令牌，自动填充（图片 ?token= 用得上）
  useEffect(() => {
    let alive = true
    api
      .getAuthStatus()
      .then((s) => {
        if (!alive) return
        if (s.token) setToken(s.token)
        setAuthState(s.authorized ? 'ok' : 'required')
        if (!s.authorized) setAuthMessage('该服务已开启访问令牌保护，请填写令牌后继续')
      })
      .catch((e) => {
        if (!alive) return
        setAuthState('required')
        setAuthMessage((e as Error).message || '无法确认鉴权状态')
      })
    return () => {
      alive = false
    }
  }, [])

  // 初始化：鉴权通过后才加载会话列表并自动进入最近一个对话
  useEffect(() => {
    if (authState !== 'ok') return
    let cancelled = false
    api.listSessions().then((list) => {
      if (cancelled) return
      setSessions(list)
      if (list.length > 0) {
        setCurrentSession(list[0])
        loadHistory(list[0].session_id)
      }
    })
    api.getKeyStatus().then((s) => {
      if (!cancelled) setKeyConfigured(s.configured)
    })
    return () => {
      cancelled = true
    }
  }, [authState, loadHistory])

  /** 中断进行中的流（切会话/删除/卸载时必须调用，否则旧流会写进新会话的最后一条气泡） */
  const abortStream = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  // 组件卸载时中断流，避免 setState after unmount
  useEffect(() => abortStream, [abortStream])

  /** 新建对话：立即创建并切换过去（与上次对话隔离） */
  const handleCreate = useCallback(() => {
    abortStream()
    setLoading(false)
    api.createSession('genshin', `新对话 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`).then((s) => {
      setCurrentSession(s)
      setMessages([])
      setEvents([])
      api.listSessions().then(setSessions)
    })
  }, [abortStream])

  /** 删除对话：删除当前选中的会话（含历史消息） */
  const handleDelete = useCallback(
    (s: SessionInfo) => {
      if (s.session_id === currentSession?.session_id) {
        abortStream()
        setLoading(false)
      }
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
              loadHistory(next.session_id)
            }
          }
        })
      })
    },
    [currentSession, abortStream, loadHistory],
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
              // 归一 content→snippet：否则实时流式时引用摘要为空（只有刷新后才正常）
              patch((last) => ({ ...last, citations: normalizeCitations(ev.citations) }))
            }
            if (ev.type === 'usage' && ev.usage) {
              patch((last) => ({ ...last, usage: ev.usage as UsageInfo }))
            }
            // trace：一次回答的耗时/调用/检索汇总（回答下方展示，可观测性的用户可见部分）
            if (ev.type === 'trace' && ev.trace) {
              patch((last) => ({ ...last, trace: ev.trace }))
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
            // 后端在 200 流内推送 error 事件（agent 异常）；带上错误码给出可操作提示
            if (ev.type === 'error') {
              const advice = describeError(ev.code, ev.error_message)
              if (advice.openSettings) setSettingsOpen(true)
              const text = advice.hint ? `${advice.text}（${advice.hint}）` : advice.text
              patch((last) => ({ ...last, content: last.content || `错误：${text}` }))
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
        // 401：令牌失效/未配置 → 回到令牌输入页，而不是显示一句"错误：需要访问令牌"
        if (e instanceof AuthRequiredError) {
          setAuthMessage(e.message)
          setAuthState('required')
          return
        }
        // 已收到部分内容后断流：连接层已自动重试过，此处提示用户，不自动重发（避免重复生成）
        let msg: string
        if (e instanceof StreamInterruptedError) {
          msg = '连接中断（已收到部分回答）。请重新发送以继续。'
        } else if (e instanceof ApiError) {
          const advice = describeError(e.code, e.message)
          if (advice.openSettings) setSettingsOpen(true)
          msg = `错误：${advice.hint ? `${advice.text}（${advice.hint}）` : advice.text}`
        } else {
          msg = `错误：${(e as Error).message}`
        }
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
    abortStream()
    setLoading(false)
  }, [abortStream])

  /** 填写访问令牌：先校验再放行（失败会抛出 AuthRequiredError 由弹窗展示） */
  const handleUnlock = useCallback(async (token: string) => {
    setToken(token.trim())
    await api.verifyToken()
    setAuthState('ok')
  }, [])

  if (authState === 'checking') {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        正在检查访问权限…
      </div>
    )
  }

  if (authState === 'required') {
    return <AuthGate message={authMessage} onUnlock={handleUnlock} />
  }

  return (
    <div className="flex h-full">
      <SessionBar
        sessions={sessions}
        current={currentSession}
        onSelect={(s) => {
          // 切会话前必须先中断旧流，否则旧流会继续 patch 新会话的最后一条气泡
          abortStream()
          setLoading(false)
          setCurrentSession(s)
          setEvents([])
          loadHistory(s.session_id)
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

/** 访问令牌输入页：仅在服务被非本机访问且开启了令牌保护时出现 */
function AuthGate({
  message,
  onUnlock,
}: {
  message: string
  onUnlock: (token: string) => Promise<void>
}) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!value.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      await onUnlock(value)
    } catch (err) {
      setError((err as Error).message || '令牌不正确')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form onSubmit={submit} className="app-card w-full max-w-sm p-6">
        <h1 className="gradient-text mb-1 text-lg font-bold">需要访问令牌</h1>
        <p className="mb-4 text-xs leading-relaxed text-gray-500">
          {message || '该服务已开启访问令牌保护。'}令牌保存在运行服务的机器上：
          <code className="mx-1 rounded bg-gray-100 px-1">backend/app_data/.api_token</code>
          （或部署时设置的 <code className="rounded bg-gray-100 px-1">API_TOKEN</code> 环境变量）。
        </p>
        <label className="mb-1 block text-xs text-gray-500" htmlFor="api-token">
          访问令牌
        </label>
        <input
          id="api-token"
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="粘贴令牌"
          className="mb-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-blue-400"
          autoFocus
        />
        {error && <p className="mb-2 text-xs text-red-500">{error}</p>}
        <button type="submit" disabled={busy || !value.trim()} className="btn-brand w-full rounded-lg py-2 text-sm disabled:opacity-50">
          {busy ? '校验中…' : '进入'}
        </button>
      </form>
    </div>
  )
}
