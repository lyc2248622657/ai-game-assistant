import { useState } from 'react'
import type { ChatMessage } from '../types'
import { api } from '../api/client'
import { renderMarkdown } from '../utils/markdown'

interface Props {
  messages: ChatMessage[]
  loading: boolean
  gameId: string | null
  onSend: (text: string) => void
}

/** 聊天窗口：消息流 + 输入框（SSE 流式渲染接入点）
 *  正文经 renderMarkdown 渲染：粗体/斜体/行内代码/URL 自动转超链接（新标签打开）
 */
export function ChatWindow({ messages, loading, gameId, onSend }: Props) {
  const [input, setInput] = useState('')
  const [feedbacks, setFeedbacks] = useState<Set<string>>(new Set())

  const submit = () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    onSend(text)
  }

  const submitFeedback = async (entity: string) => {
    if (loading || feedbacks.has(entity)) return
    try {
      await api.submitFeedback(gameId || 'genshin', entity, '用户从"相关实体提示"提交补充请求')
      setFeedbacks((prev) => new Set(prev).add(entity))
    } catch {
      // 静默失败，不打断对话
    }
  }

  const fmtPlay = (play?: number) => {
    if (!play && play !== 0) return ''
    if (play >= 10000) return `${(play / 10000).toFixed(1)}万`
    return String(play)
  }

  return (
    <div className="flex flex-1 flex-col rounded-lg border bg-white">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-center text-sm text-gray-400">
            输入问题开始对话，例如：胡桃的技能数值 / 银灰的培养材料 / 天空之翼适合谁
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[82%] rounded-xl px-4 py-2.5 text-sm shadow-sm ${
                m.role === 'user'
                  ? 'bg-blue-600 text-white shadow-blue-200'
                  : 'border border-gray-100 bg-white text-gray-800'
              }`}
            >
              {m.role === 'assistant' && m.image_url ? (
                // 助手消息带实体头像：圆形图片 + 文字并排
                <div className="mb-2 flex items-start gap-3">
                  <img
                    src={m.image_url}
                    alt="实体头像"
                    className="h-24 w-24 shrink-0 rounded-xl border border-gray-100 object-cover shadow-sm"
                    onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                  />
                  <div className="min-w-0 flex-1">{renderMarkdown(m.content)}</div>
                </div>
              ) : (
                // 正文：Markdown 渲染（URL 自动变超链接）
                <div className={m.role === 'assistant' ? 'min-w-0' : 'whitespace-pre-wrap'}>{renderMarkdown(m.content)}</div>
              )}
              {m.role === 'assistant' && m.guides && m.guides.videos?.length > 0 && (
                <div className="mt-2.5 overflow-hidden rounded-xl border border-gray-200">
                  <div className="flex items-center justify-between bg-gradient-to-r from-red-50 to-orange-50 px-3 py-1.5">
                    <span className="text-xs font-semibold text-red-600">📺 攻略视频</span>
                    {m.guides.api_ok && (
                      <span className="text-[10px] text-gray-400">来自 B站搜索结果</span>
                    )}
                  </div>
                  {m.guides.videos.map((v, vi) => (
                    <a
                      key={v.url}
                      href={v.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center gap-2 border-t border-gray-100 px-3 py-2 text-xs transition hover:bg-gray-50"
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-red-50 text-[10px] font-bold text-red-500">
                        {vi + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-gray-700 group-hover:text-red-600">{v.title}</span>
                        <span className="mt-0.5 flex items-center gap-2 text-[10px] text-gray-400">
                          <span>{v.author}</span>
                          {v.duration && <span>⏱ {v.duration}</span>}
                          {fmtPlay(v.play) !== '' && <span>▶ {fmtPlay(v.play)}</span>}
                        </span>
                      </span>
                      <span className="shrink-0 rounded-md bg-red-500 px-2 py-1 text-[10px] font-medium text-white shadow-sm transition group-hover:bg-red-600">
                        观看
                      </span>
                    </a>
                  ))}
                  <div className="flex flex-wrap gap-1.5 border-t border-gray-100 bg-gray-50/60 px-3 py-2">
                    {m.guides.search_url && (
                      <a
                        href={m.guides.search_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-[11px] text-blue-600 transition hover:bg-blue-100"
                      >
                        B站搜索更多 ↗
                      </a>
                    )}
                    {m.guides.wiki_url && (
                      <a
                        href={m.guides.wiki_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded-full border border-green-200 bg-green-50 px-3 py-1 text-[11px] text-green-700 transition hover:bg-green-100"
                      >
                        官方 wiki 攻略页 ↗
                      </a>
                    )}
                  </div>
                </div>
              )}
              {m.role === 'assistant' && m.related_entities && m.related_entities.length > 0 && (
                <div className="mt-2 border-t border-gray-100 pt-2">
                  <div className="text-xs text-gray-500">
                    相关实体：{m.related_entities.join('、')}
                  </div>
                  <button
                    onClick={() => submitFeedback(m.related_entities?.[0] || '')}
                    disabled={loading || feedbacks.has(m.related_entities?.[0] || '')}
                    className="mt-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-700 transition hover:bg-amber-100 disabled:opacity-50"
                  >
                    {feedbacks.has(m.related_entities?.[0] || '') ? '已提交补充请求 ✓' : '补充资料'}
                  </button>
                </div>
              )}
              {m.role === 'assistant' && m.suggestions && m.suggestions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2 border-t border-gray-100 pt-2">
                  {m.suggestions.map((s) => (
                    <button
                      key={s}
                      onClick={() => onSend(s)}
                      disabled={loading}
                      className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs text-blue-600 transition hover:bg-blue-100 disabled:opacity-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {m.role === 'assistant' && m.usage && (
                <div className="mt-1.5 border-t border-gray-100 pt-1 text-[11px] text-gray-400">
                  ⚡ 本轮消耗 {m.usage.total_tokens.toLocaleString()} token（{m.usage.llm_calls} 次调用）
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
            正在思考…
          </div>
        )}
      </div>
      <div className="flex gap-2 border-t p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="输入消息，Enter 发送（可问原神或明日方舟）"
          className="flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={submit}
          disabled={loading || !input.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
        >
          发送
        </button>
      </div>
    </div>
  )
}
