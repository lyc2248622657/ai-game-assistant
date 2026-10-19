import type { ChatMessage, Citation, StoredCitation, StoredMessage } from '../types'

/** 引用归一：把两种来源统一成前端 `Citation`。
 *
 *  - 历史接口（GET /api/sessions/{id}/messages）落库的键是 `snippet`
 *  - SSE `citations` 事件推的是图状态的原始 dict，键是 `content`
 *
 * 只在一处归一，避免"刷新后正常、实时流式却空白"这类只覆盖单条路径的修复漏网。
 */
export function normalizeCitations(
  raw?: Array<StoredCitation | Citation>,
): Citation[] | undefined {
  if (!raw?.length) return undefined
  return raw.map((c) => {
    const s = c as StoredCitation
    return {
      doc_id: s.doc_id ?? '',
      title: s.title ?? '',
      snippet: s.snippet ?? s.content ?? '',
      source: s.source,
    }
  })
}

/** 历史消息 → ChatMessage（保留引用与配图，缺了就会在重开会话时丢卡片） */
export function mapHistory(messages: StoredMessage[]): ChatMessage[] {
  return messages.map((m) => ({
    role: m.role === 'user' ? 'user' : 'assistant',
    content: m.content,
    citations: normalizeCitations(m.citations),
    images: m.images?.length ? m.images : undefined,
  }))
}
