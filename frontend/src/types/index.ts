// 与后端 schemas/chat.py 对应的类型定义

export interface GameInfo {
  game_id: string
  name: string
  enabled: boolean
  description?: string
}

export interface SessionInfo {
  session_id: string
  game_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Citation {
  doc_id: string
  title: string
  snippet: string
  source?: string
}

export interface GuideInfo {
  videos: Array<{ title: string; url: string; author?: string; duration?: string; play?: number }>
  search_url?: string
  wiki_url?: string
  api_ok?: boolean
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  usage?: UsageInfo
  /** 本轮 trace：耗时/调用次数/检索次数（回答下方展示） */
  trace?: TraceInfo
  /** 用户随消息上传的截图：本地路径（提交给后端 image_path） */
  image_path?: string
  /** 用户截图的预览 URL（/uploads/xxx，前端渲染缩略图） */
  user_image?: string
  /** 实体头像图片 URL（问角色→角色图、问武器→武器图） */
  image_url?: string
  /** 回答相关图片列表（主实体 + 关联实体多图，A/B 全覆盖） */
  images?: string[]
  /** 猜测适配选项（可点击追问按钮，如"查看该角色适配队伍"） */
  suggestions?: string[]
  /** 资料未收录时的相关实体提示（前端渲染"补充资料"入口） */
  related_entities?: string[]
  /** 攻略检索结果（B站视频列表 + 跳转链接） */
  guides?: GuideInfo
}

/** 后端持久化的引用项：新数据用 snippet，旧数据可能是 content（渲染前需归一） */
export interface StoredCitation {
  doc_id?: string
  title?: string
  snippet?: string
  content?: string
  source?: string
}

/** GET /api/sessions/{id}/messages 返回的持久化消息形状 */
export interface StoredMessage {
  role: string
  content: string
  citations?: StoredCitation[]
  images?: string[]
}

/** 一轮回答的结构化 trace（可观测：总耗时 / 调用次数 / 检索与工具次数） */
export interface TraceInfo {
  total_ms: number
  llm_calls: number
  tokens: number
  retrieval_docs: number
  tool_calls: number
  citations: number
  nodes: Array<{ node: string; ms: number; runs: number }>
}

/** 本轮对话的 LLM token 消耗（后端 usage 回调统计） */
export interface UsageInfo {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  llm_calls: number
}

/** RAG 检索来源卡片（retrieval 事件 docs，决策链路深化：带相似度与摘要） */
export interface RetrievalDoc {
  title: string
  source?: string
  score?: number
  snippet?: string
}

/** Agent 决策链路事件（对应后端 AgentEvent） */
export type AgentEventType =
  | 'session'
  | 'agent_start'
  | 'agent_end'
  | 'tool_call'
  | 'tool_result'
  | 'retrieval'
  | 'tasks'
  | 'subagent'
  | 'replan'
  | 'answer'
  | 'suggestions'
  | 'image'
  | 'related_entities'
  | 'guides'
  | 'citations'
  | 'trace'
  | 'usage'
  | 'error'
  | 'done'

/** 任务分解子任务（plan 阶段 LLM 拆分的复合意图清单） */
export interface SubTask {
  task: string
  description?: string
  suggested_tool?: string
  target?: string
}

export interface AgentEvent {
  type: AgentEventType
  node_name?: string
  message?: string
  summary?: string
  tool_name?: string
  arguments?: Record<string, unknown>
  result?: string
  docs?: RetrievalDoc[]
  /** 事件产生时刻（后端统一打点，前端据此统计节点耗时/进行中高亮） */
  ts?: number
  tasks?: SubTask[]
  /** 多智能体委派：被委派的子代理标识（原神子代理/明日方舟子代理/通用知识子代理） */
  identity?: string
  delegate_to?: string
  brief?: string
  /** 动态重规划：补充执行的子任务清单 */
  remaining?: SubTask[]
  delta?: string
  suggestions?: string[]
  image_url?: string
  /** 相关图片列表（image 事件，主实体 + 关联实体多图） */
  images?: string[]
  related_entities?: string[]
  guides?: GuideInfo
  citations?: Citation[]
  usage?: UsageInfo
  trace?: TraceInfo
  session_id?: string
  code?: number
  error_message?: string
}

// ---- 管理控制台（方向 1）----

/** 向量集合（Chroma collection 名称 + 块数） */
export interface VectorCollection {
  name: string
  count: number
}

/** 集合统计（按文档/来源分布 + 孤儿块） */
export interface VectorStats {
  collection: string
  total: number
  by_doc: Record<string, number>
  by_source: Record<string, number>
  orphan_docs: string[]
  orphan_chunk_count: number
}

/** 文档问答已入库文档（data/documents/*.md） */
export interface DocqaDocument {
  name: string
  path: string
  size: number
}
