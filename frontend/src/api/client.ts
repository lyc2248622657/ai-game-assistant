// 后端 API 客户端：REST + SSE 流式

import type {
  AgentEvent,
  DocqaDocument,
  GameInfo,
  SessionInfo,
  VectorCollection,
  VectorStats,
} from '../types'

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
    request<{ messages: Array<{ role: string; content: string; citations?: unknown[]; images?: string[] }> }>(
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

  // 多模态：上传游戏截图（返回本地路径供聊天消息携带 + 预览 URL）
  uploadImage: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${BASE}/vision/upload`, { method: 'POST', body: form }).then(async (res) => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.message || `上传失败: ${res.status}`)
      }
      return res.json() as Promise<{ ok: boolean; image_path: string; image_url: string; size: number }>
    })
  },

  // ---- 管理控制台：向量库运维（增量更新 / 脏数据清理 / 检索测试） ----

  listCollections: () => request<{ collections: VectorCollection[] }>('/vector/collections'),

  getVectorStats: (collection: string) =>
    request<VectorStats>(`/vector/stats?collection=${encodeURIComponent(collection)}`),

  deleteVectorDoc: (collection: string, doc: string) =>
    request<{ collection: string; doc: string; deleted_chunks: number }>(
      `/vector/documents/${encodeURIComponent(collection)}/${encodeURIComponent(doc)}`,
      { method: 'DELETE' },
    ),

  purgeVector: (collection: string) =>
    request<{ collection: string; purged_chunks: number }>(
      `/vector/purge?collection=${encodeURIComponent(collection)}`,
      { method: 'POST' },
    ),

  rebuildVectorDoc: (doc: string) =>
    request<{ ok: boolean; name?: string; chunks?: number; deleted_chunks?: number; message?: string }>(
      `/vector/documents/${encodeURIComponent(doc)}/rebuild`,
      { method: 'POST' },
    ),

  searchVector: (gameId: string, query: string, topK = 4) =>
    request<{
      game_id: string
      query: string
      docs: Array<{ doc_id: string; title: string; content: string; source?: string; score?: number }>
    }>('/vector/search', {
      method: 'POST',
      body: JSON.stringify({ game_id: gameId, query, top_k: topK }),
    }),

  // 文档问答库（FDE 演示）
  listDocDocuments: () => request<{ documents: DocqaDocument[] }>('/docqa/documents'),

  // 养成计划（写操作闭环回读：保存的计划按会话查询/删除）
  listPlans: (sessionId: string) =>
    request<{
      plans: Array<{
        id: number
        session_id: string
        game_id: string
        character: string
        goal: string
        status: string
        created_at: string
        plan: any
      }>
    }>(`/plans?session_id=${encodeURIComponent(sessionId)}`),
  deletePlan: (planId: number) =>
    request<{ ok: boolean }>(`/plans/${planId}`, { method: 'DELETE' }),
}

/** 解析单段 SSE 帧（event 行 + data 行），供流式解析与单元测试复用 */
export function parseSSEFrame(raw: string): { event: string; data: string } {
  let event = 'message'
  let data = ''
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  return { event, data }
}

/** 连接层失败（可自动重试）：fetch 异常 / HTTP 5xx / 无响应体 / 未收到任何事件即断流 */
export class StreamConnectionError extends Error {}
/** 已收到事件后流中断（服务端异常或半途断开，交由 UI 提示，不自动重发以避免重复生成） */
export class StreamInterruptedError extends Error {}

async function streamOnce(
  gameId: string | null,
  message: string,
  sessionId: string | null,
  imagePath: string | null,
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_id: gameId, message, session_id: sessionId, image_path: imagePath }),
      signal,
    })
  } catch (e) {
    if (signal?.aborted) throw e
    throw new StreamConnectionError(`连接失败: ${(e as Error).message}`)
  }
  if (!res.ok) {
    if (res.status >= 500) throw new StreamConnectionError(`服务暂时不可用 (${res.status})`)
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.message || `聊天请求失败: ${res.status}`)
  }
  if (!res.body) throw new StreamConnectionError('当前环境不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let received = 0

  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
      if (chunk.done) break
      if (chunk.value) buf += decoder.decode(chunk.value, { stream: true })
    } catch (e) {
      if (signal?.aborted) throw e
      if (received > 0) throw new StreamInterruptedError('连接中断（已收到部分内容）')
      throw new StreamConnectionError(`流读取失败: ${(e as Error).message}`)
    }

    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const { event, data } = parseSSEFrame(raw)
      if (!data) continue
      try {
        const parsed = JSON.parse(data)
        received++
        onEvent({ type: event, ...parsed } as AgentEvent)
      } catch {
        /* 忽略无法解析的帧 */
      }
    }
  }
}

/**
 * 流式聊天：通过 SSE 接收 Agent 事件（逐节点实时推送）。
 * 连接层失败自动重试（最多 3 次，指数退避）；已收到事件后断流则抛出
 * StreamInterruptedError 交由 UI 提示，避免重复生成。
 */
export async function streamChat(
  gameId: string | null,
  message: string,
  sessionId: string | null,
  imagePath: string | null,
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const maxAttempts = 3
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      await streamOnce(gameId, message, sessionId, imagePath, onEvent, signal)
      return
    } catch (e) {
      if (signal?.aborted) throw e
      if (e instanceof StreamInterruptedError) throw e
      if (!(e instanceof StreamConnectionError)) throw e
      if (attempt >= maxAttempts - 1) throw e
      await new Promise((r) => setTimeout(r, 500 * 2 ** attempt))
    }
  }
}
