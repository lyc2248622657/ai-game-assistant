"""聊天接口的数据模型：请求、SSE 事件、响应"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """发送一条用户消息（多游戏统一对话框：game_id 由 Agent 自动判别，可缺省）"""

    game_id: Optional[str] = Field(None, description="游戏标识（可空：Agent 自动判别原神/明日方舟）")
    message: str = Field(..., min_length=1, max_length=4000, description="用户消息")
    session_id: Optional[str] = Field(None, description="会话 ID；缺省时自动新建")


class GuideInfo(BaseModel):
    """攻略检索结果（B站视频列表 + 搜索直达 + wiki 攻略页）"""

    videos: list[dict] = []
    search_url: Optional[str] = None
    wiki_url: Optional[str] = None
    api_ok: bool = False


class ChatResponse(BaseModel):
    """完整回答（非流式场景 / 兼容响应）"""

    session_id: str
    game_id: str
    answer: str
    citations: list["Citation"] = []
    suggestions: list[str] = []       # 猜测适配选项（前端渲染为可点击追问按钮）
    image_url: Optional[str] = None   # 实体头像图片（角色图/武器图）
    related_entities: list[str] = []  # 未收录时相关实体提示（前端渲染"补充资料"入口）
    guides: Optional[GuideInfo] = None  # 攻略检索结果（视频跳转/链接）
    usage: Optional[dict] = None  # 本轮对话 LLM token 消耗（input/output/total/calls）


class Citation(BaseModel):
    """回答引用的知识条目"""

    doc_id: str
    title: str
    snippet: str
    source: str = ""


# --- SSE 事件模型 ---
# 事件流格式：data: {json}\n\n，event 类型区分阶段
EventType = Literal[
    "session",     # 会话就绪，携带 session_id
    "agent_start", # 节点开始（node_name, message）
    "agent_end",   # 节点结束（node_name, summary）
    "tool_call",   # 工具调用（tool_name, arguments）
    "tool_result", # 工具返回（tool_name, result 摘要）
    "retrieval",   # 检索结果（docs 摘要）
    "answer",      # 回答增量（delta 文本，流式）
    "suggestions", # 猜测适配选项（suggestions 数组，前端渲染为可点击按钮）
    "image",       # 实体头像图片（image_url）
    "related_entities", # 未收录相关实体提示
    "guides",      # 攻略检索结果（视频跳转/链接）
    "citations",   # 最终引用列表
    "usage",       # 本轮对话 token 消耗
    "error",       # 错误（code, message）
    "done",        # 流程结束
]


class AgentEvent(BaseModel):
    """Agent 决策过程事件（用于前端决策链路时间线）"""

    type: EventType
    node_name: Optional[str] = None
    message: Optional[str] = None
    summary: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[dict] = None
    result: Optional[str] = None
    docs: Optional[list[dict]] = None
    delta: Optional[str] = None
    suggestions: Optional[list[str]] = None
    image_url: Optional[str] = None
    related_entities: Optional[list[str]] = None
    guides: Optional[dict] = None
    citations: Optional[list[Citation]] = None
    session_id: Optional[str] = None
    usage: Optional[dict] = None
    code: Optional[int] = None
    error_message: Optional[str] = None


class SessionCreate(BaseModel):
    """新建会话请求"""

    game_id: str = Field(..., description="会话所属游戏")
    title: Optional[str] = Field(None, max_length=100, description="会话标题")


class SessionInfo(BaseModel):
    """会话元信息"""

    session_id: str
    game_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class GameInfo(BaseModel):
    """游戏信息（前端游戏选择器数据源）"""

    game_id: str
    name: str
    enabled: bool
    description: str = ""
