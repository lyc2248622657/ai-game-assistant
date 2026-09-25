"""MCP Server 冒烟测试：列工具 + 调用两个核心工具（stdio 客户端）"""
from __future__ import annotations

import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_CMD = ["D:\\PythonProject\\ai-game-assistant\\backend\\.venv\\Scripts\\python.exe",
              "D:\\PythonProject\\ai-game-assistant\\backend\\mcp_server.py"]


async def main() -> None:
    params = StdioServerParameters(command=SERVER_CMD[0], args=SERVER_CMD[1:], cwd="D:\\PythonProject\\ai-game-assistant\\backend")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("[init] server:", init.server_info.name, init.server_info.version)

            tools = await session.list_tools()
            print("[tools]", [t.name for t in tools.tools])

            r1 = await session.call_tool("list_games", {})
            print("[list_games]", r1.content[0].text[:200])

            r2 = await session.call_tool("query_game_entity", {
                "game_id": "arknights", "entity_type": "character", "name": "能天使",
            })
            data = json.loads(r2.content[0].text)
            ent = data.get("entity", {})
            print("[query] found:", data.get("found"), "| name:", ent.get("name"),
                  "| role:", ent.get("role"), "| rarity:", ent.get("rarity"))

            r3 = await session.call_tool("search_knowledge", {
                "game_id": "genshin", "query": "雷系副C有哪些", "top_k": 2,
            })
            raw3 = r3.content[0].text
            print("[retrieve] raw[:300]:", raw3[:300])


if __name__ == "__main__":
    asyncio.run(main())
