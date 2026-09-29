// 后端 API 客户端：REST + SSE 流式

import type { AgentEvent, GameInfo, SessionInfo } from '../types'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.message || `请求失败: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  // 游戏
  listGames: () => request<{ games: GameInfo[] }>('/games'),

  // 游戏重大事件（版本更新/前瞻/活动/卡池倒计时）
  listEvents: () => request<{ games: any[] }>('/events'),

  // 会话
  listSessions: (gameId?: string) =>
    request<SessionInfo[]>(`/sessions${gameId ? `?game_id=${gameId}` : ''}`),
  createSession: (gameId: string, title?: string) =>
    request<SessionInfo>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ game_id: gameId, title }),
    }),
  deleteSession: (sessionId: string) =>
    request<{ ok: boolean }>(`/sessions/${sessionId}`, { method: 'DELETE' }),
  getMessages: (sessionId: string) =>
    request<{ messages: Array<{ role: string; content: string; citations?: unknown[] }> }>(
      `/sessions/${sessionId}/messages`,
    ),

  // 知识库补充（资料未收录 → 提交补充请求，待人工核实入库）
  submitFeedback: (gameId: string, entityName: string, note?: string) =>
    request<{ ok: boolean }>('/knowledge/feedback', {
      method: 'POST',
      body: JSON.stringify({ game_id: gameId, entity_name: entityName, note }),
    }),

  // 应用内设置：API Key（只返回打码，明文明文仅在保存时提交一次）
  getKeyStatus: () =>
    request<{ configured: boolean; source?: string | null; model?: string; masked_key?: string }>(
      '/settings/key',
    ),
  saveKey: (apiKey: string, model: string) =>
    request<{ ok: boolean; model: string; masked_key: string; message: string }>('/settings/key', {
      method: 'PUT',
      body: JSON.stringify({ api_key: apiKey, model }),
    }),
  testKey: (apiKey: string, model: string) =>
    request<{ ok: boolean; message: string }>('/settings/key/test', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey, model }),
    }),
}

/**
 * 流式聊天：通过 SSE 接收 Agent 事件（逐节点实时推送）。
 * 多游戏统一对话框：gameId 可空，由后端 Agent 自动判别游戏。
 * fetch + ReadableStream 解析 "event: xxx\ndata: {json}\n\n" 分段。
 */
export async function streamChat(
  gameId: string | null,
  message: string,
  sessionId: string | null,
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ game_id: gameId, message, session_id: sessionId }),
    signal,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.message || `聊天请求失败: ${res.status}`)
  }
  if (!res.body) throw new Error('当前环境不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      try {
        const parsed = JSON.parse(data)
        onEvent({ type: event, ...parsed } as AgentEvent)
      } catch {
        /* 忽略无法解析的帧 */
      }
    }
  }
}
