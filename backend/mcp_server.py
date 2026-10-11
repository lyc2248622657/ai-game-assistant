"""MCP 工具协议服务器：把智能体平台能力暴露为标准 MCP 工具

将项目内部能力（按需实体查询 / RAG 混合检索 / 游戏注册表）封装为
Model Context Protocol 标准工具，供任意 MCP 客户端（Claude Desktop、
Cursor、自研编排器等）通过 stdio 调用。

运行：
  cd backend && .venv\\Scripts\\python.exe mcp_server.py

客户端连接（任意 MCP 客户端，如 mcp 官方 CLI）：
  mcp dev mcp_server.py  或配置为 stdio server
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from app.knowledge.games import registry  # noqa: E402
from app.rag import document_qa, vector_admin  # noqa: E402
from app.rag.retriever import hybrid_retrieve  # noqa: E402
from app.tools.base import ToolContext  # noqa: E402
from app.tools.game_entity import QueryGameEntityTool  # noqa: E402

mcp = MCPServer("ai-game-assistant", instructions="AI 游戏助手智能体平台：查询游戏实体、检索知识库、运维向量库、企业文档问答。")

_entity_tool = QueryGameEntityTool()


def _game_by_id(game_id: str):
    return registry.get_game(game_id)


@mcp.tool()
def list_games() -> list[dict]:
    """列出当前启用的游戏（原神 / 明日方舟等）。"""
    return registry.list_games()


@mcp.tool()
def query_game_entity(game_id: str, entity_type: str, name: str) -> dict:
    """查询指定游戏中某个实体的完整信息（角色/武器/圣遗物/料理/材料）。

    Args:
        game_id: 游戏标识，如 genshin / arknights。
        entity_type: 实体类型，character | weapon | artifact | material | food。
        name: 实体名称，如 胡桃 / 能天使。
    """
    game = _game_by_id(game_id)
    ctx = ToolContext(game)
    return _entity_tool.run({"type": entity_type, "name": name}, ctx)


@mcp.tool()
def search_knowledge(game_id: str, query: str, top_k: int = 4) -> list[dict]:
    """在指定游戏的知识库中做混合检索（名称置顶 + 向量召回 + 关键词兜底）。

    Args:
        game_id: 游戏标识，如 genshin / arknights。
        query: 自然语言问题或关键词，如 雷系副C有哪些。
        top_k: 返回条数上限。
    """
    game = _game_by_id(game_id)
    return hybrid_retrieve(game, query, top_k=top_k)


# ---- 向量库运维（RAG 岗：增量更新 / 脏数据清理）----

@mcp.tool()
def list_vector_collections() -> list[dict]:
    """列出全部向量集合及块数（genshin_kb / arknights_kb / documents / user_memory）。"""
    return vector_admin.list_collections()


@mcp.tool()
def vector_stats(collection: str = "documents") -> dict:
    """集合统计：总量 / 按文档分布 / 按来源分布 / 孤儿块（源文件已删除的残留向量）。

    Args:
        collection: 集合名，如 documents / genshin_kb / arknights_kb。
    """
    return vector_admin.collection_stats(collection)


@mcp.tool()
def delete_vector_document(collection: str, doc: str) -> dict:
    """按文档名删除其全部向量块（脏数据清理；documents 集合按文档名，游戏集合按 game 名）。

    Args:
        collection: 集合名，如 documents / genshin_kb。
        doc: 文档名或游戏标识，如 示例公司员工制度手册 / genshin。
    """
    return vector_admin.delete_document(collection, doc)


# ---- 企业文档问答（FDE 演示：客户问题 → 可交付产品）----

@mcp.tool()
def list_documents() -> list[dict]:
    """列出已入库的企业文档（data/documents/*.md）。"""
    return document_qa.list_documents()


@mcp.tool()
def ingest_document(name: str, content: str) -> dict:
    """导入企业文档（md/txt 文本）并分块向量化入库。

    Args:
        name: 文档名（将作为文件名与检索元数据）。
        content: 文档正文。
    """
    return document_qa.ingest_document(name, content)


@mcp.tool()
def ask_document(question: str, top_k: int = 4) -> dict:
    """企业文档问答：检索 → 带引用上下文 → LLM 回答（资料未覆盖内容如实标注『资料未收录』）。

    Args:
        question: 自然语言问题，如 病假需要什么证明。
        top_k: 引用条数上限。
    """
    return document_qa.ask(question, top_k=top_k)


if __name__ == "__main__":
    mcp.run(transport="stdio")