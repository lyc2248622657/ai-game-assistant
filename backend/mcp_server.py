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
from app.rag.retriever import hybrid_retrieve  # noqa: E402
from app.tools.base import ToolContext  # noqa: E402
from app.tools.game_entity import QueryGameEntityTool  # noqa: E402

mcp = MCPServer("ai-game-assistant", instructions="AI 游戏助手智能体平台：按需查询游戏实体、检索知识库。")

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


if __name__ == "__main__":
    mcp.run(transport="stdio")