# MCP 工具演示（Model Context Protocol）

> 把 ai-game-assistant 的智能体平台能力暴露为标准 MCP 工具，任意 MCP 客户端（Claude Desktop / Cursor / 自研编排器）可通过 stdio 调用。
> 对齐岗位信号：深圳德恩「MCP 工具调用、A2A 多智能体协同」（13-14K）、广州快创「Dify/Coze agent 经验」。

## 一、已注册工具（10 个）

| 工具 | 说明 | 演示命令 |
|---|---|---|
| `list_games` | 列出启用游戏 | `list_games {}` |
| `query_game_entity` | 游戏实体查询（角色/武器/圣遗物/料理/材料） | `query_game_entity {"game_id":"arknights","entity_type":"character","name":"能天使"}` |
| `search_knowledge` | 游戏知识库混合检索（名称置顶+向量+BM25） | `search_knowledge {"game_id":"genshin","query":"雷系副C有哪些","top_k":2}` |
| `list_vector_collections` | 列出全部向量集合及块数 | `list_vector_collections {}` |
| `vector_stats` | 集合统计：总量/按文档/按来源/孤儿块 | `vector_stats {"collection":"documents"}` |
| `delete_vector_document` | 按文档删除向量块（脏数据清理） | `delete_vector_document {"collection":"documents","doc":"旧文档"}` |
| `list_documents` | 已入库企业文档清单 | `list_documents {}` |
| `ingest_document` | 企业文档导入并向量化 | `ingest_document {"name":"制度","content":"第一条…"}` |
| `ask_document` | 企业文档问答（带引用，未收录如实标注） | `ask_document {"question":"报销流程是什么？"}` |
| `run_agent_task` | **A2A 多智能体协同**：分解→派发三域智能体→汇总带来源 | `run_agent_task {"task":"统计文档库多少块，顺便查能天使强度"}` |

A2A 协同（最后一个工具）的架构与端到端验证见 `docs/A2A-DEMO.md`。

## 二、启动与连接

```powershell
cd D:\PythonProject\ai-game-assistant\backend
.\.venv\Scripts\python.exe mcp_server.py            # stdio 模式
```

任意 MCP 客户端配置 stdio server：

```json
{
  "mcpServers": {
    "ai-game-assistant": {
      "command": "D:\\PythonProject\\ai-game-assistant\\backend\\.venv\\Scripts\\python.exe",
      "args": ["D:\\PythonProject\\ai-game-assistant\\backend\\mcp_server.py"],
      "cwd": "D:\\PythonProject\\ai-game-assistant\\backend"
    }
  }
}
```

## 三、端到端验证（2026-10-11，mcp_client_test.py）

```
[init] server: ai-game-assistant
[tools] 10 个工具
[query] found: True | name: 能天使 | role: 狙击（速射手）| rarity: 6
[retrieve] genshin 混合检索命中（doc_id=character_旅行者/草 等）
[collections] arknights_kb 460 / documents 0 / genshin_kb 233 / user_memory 19
[stats] documents: total=0, by_doc={}, orphan=0（未入库任何客户文档时如实返回空；入库后按文档统计）
[ask_document] retrieved: 0 | answer: 资料未收录…（未入库时如实标注，不编造）
[a2a] subtasks: ['game_agent','vector_agent'] | 汇总带来源
```

## 四、说明

- 服务端仅封装项目内已有能力（实体工具 / RAG 混合检索 / 向量运维 / 文档问答），无额外数据依赖；
- 运维类工具（delete_vector_document / vector_stats）对应 RAG 岗「向量库维护、脏数据清理」硬要求，CLI 等价入口：`scripts\vector_admin.py`。
