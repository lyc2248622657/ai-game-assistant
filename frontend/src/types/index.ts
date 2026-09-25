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
  /** 实体头像图片 URL（问角色→角色图、问武器→武器图） */
  image_url?: string
  /** 猜测适配选项（可点击追问按钮，如"查看该角色适配队伍"） */
  suggestions?: string[]
  /** 资料未收录时的相关实体提示（前端渲染"补充资料"入口） */
  related_entities?: string[]
  /** 攻略检索结果（B站视频列表 + 跳转链接） */
  guides?: GuideInfo
}

/** 本轮对话的 LLM token 消耗（后端 usage 回调统计） */
export interface UsageInfo {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  llm_calls: number
}

// Agent 决策链路事件（对应后端 AgentEvent）
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
  docs?: Array<Record<string, unknown>>
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
  related_entities?: string[]
  guides?: GuideInfo
  citations?: Citation[]
  usage?: UsageInfo
  session_id?: string
  code?: number
  error_message?: string
}
