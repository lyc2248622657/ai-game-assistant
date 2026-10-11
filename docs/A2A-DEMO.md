# A2A 多智能体协同演示（Agent-to-Agent）

> 一个复合请求 → 协调者任务分解 → 派发独立智能体执行（游戏域 / 企业文档域 / 向量运维域）→ 汇总带来源回答。
> 对齐岗位 22（深圳德恩，南方电网项目点名 **RAG+MCP+A2A**）与「企业级智能体平台（Dify/RagFlow/LangGraph）实操成标配」信号。

## 一、架构

```
外部客户端 / MCP 客户端
        │  run_agent_task("查能天使强度 + 顺便问病假证明")
        ▼
A2AOrchestrator（app/agents/a2a.py）
  decompose   →  LLM 按能力清单分解子任务（失败自动降级关键词规则）
  dispatch    →  派发独立智能体（单点失败不阻断整体，降级标记 error）
  synthesize  →  LLM 汇总带来源（[agent] 标注；失败降级结构化拼接）
        │
        ├─ game_agent    游戏域：实体查询（QueryGameEntityTool）+ 混合检索（hybrid_retrieve）
        ├─ doc_agent     企业文档域：document_qa.ask（带引用，未收录如实标注）
        └─ vector_agent  向量运维域：vector_admin 统计（总量/按文档/孤儿块）
```

与 LangGraph 图内编排（supervisor→子代理→replan→reflect）互补：A2A 展示**协议级多智能体协同**——多个独立智能体通过协调者协作解决复合任务，并整体暴露为单个 MCP 工具（A2A over MCP）。

## 二、运行

```powershell
cd D:\PythonProject\ai-game-assistant\backend

# LLM 主路径（分解 + 汇总都用 DeepSeek）
.\.venv\Scripts\python.exe scripts\a2a_demo.py

# 全离线（关键词分解 + 结构化汇总，演示链路不依赖 key）
.\.venv\Scripts\python.exe scripts\a2a_demo.py --no-llm

# 经 MCP 调用（工具名 run_agent_task，第 10 个工具）
.\.venv\Scripts\python.exe scripts\mcp_client_test.py
```

## 三、端到端验证（2026-10-11）

请求：`帮我查一下明日方舟能天使的强度，顺便问一下员工病假超过几天需要开诊断证明`

- LLM 分解：`[doc_agent 企业文档问答, game_agent 游戏知识查询]`
- 派发：doc_agent → 病假超 3 天需医院诊断证明（引用 4 条）；game_agent → 能天使检索命中（能天使/新约能天使）
- LLM 汇总：分点回答、逐条标注来源 `[game_agent]` / `[doc_agent]`、未收录内容如实说明

请求：`统计一下文档库和方舟知识库分别有多少块`

- 分解：`[vector_agent 向量库统计]`；统计：documents 共 30 块、孤儿块 0（按文档 {示例公司员工制度手册: 30}）

离线模式（--no-llm）同样可跑：关键词分解 → 结构化拼接。

## 四、说明

- 智能体注册表：`app/agents/a2a.py` 的 `SUB_AGENTS`（name / capabilities / run），新增子智能体只需注册一项；
- 降级链：LLM 分解失败 → 关键词规则；LLM 汇总失败 → 结构化拼接；单个子智能体异常 → 该子任务标记 error，其余继续；
- 单测 10 项（`tests/test_a2a.py`）：LLM 分解解析 / 关键词兜底 / 三域派发 / 未知智能体降级 / LLM 汇总 / 结构化汇总 / 全流程闭环；
- 全量 pytest 91 passed。
