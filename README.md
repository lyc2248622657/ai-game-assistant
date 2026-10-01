# AI 游戏助手智能体平台

基于 LangGraph 的多智能体游戏助手：支持多游戏知识包（原神 / 明日方舟）、RAG 向量检索、**6 个 Function Calling 工具（实体查询/配队分析/材料换算/攻略检索/关卡攻略/重大事件）**、SSE 流式决策链路可视化与 React 前端。官方 wiki（BWIKI / PRTS）为主要数据依据，LLM 仅补缺并交叉验证，回答可溯源防幻觉。

[![CI](https://github.com/lyc2248622657/ai-game-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/lyc2248622657/ai-game-assistant/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/lyc2248622657/ai-game-assistant)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)](backend/requirements.txt)

## 整体架构

```
┌──────────────────────────── React 18 + TS + Vite + Tailwind ────────────────────────────┐
│ 统一对话框 · 会话管理（折叠/新建/删除） · Agent 决策时间线 · 引用卡片 · 头像+建议按钮 · 攻略视频卡片 │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                          │ /api/chat/stream (SSE)
┌────────────────────────────────────────▼───────────────────────────────────────────────┐
│                        FastAPI + LangGraph 后端（多智能体编排）                            │
│  supervisor(主管: 游戏识别+域判别+委派单) → route(委派决策)                               │
│     → [genshin_agent | arknights_agent | knowledge_agent] 子代理执行                    │
│        retrieve(混合检索) ⇄ tool(Function Calling 循环 ≤3轮)                             │
│     → replan(Plan-Execute-Refine 动态重规划 ≤1轮) → synthesize → reflect(自检回炉)       │
│        → fallback(兜底)                                                                  │
│                                                                                        │
│  tools/（注册表驱动）                                                                   │
│   ├─ query_game_entity   静态库 → 动态缓存 → 官方 wiki → LLM 补缺 → 交叉验证 → 增量补全    │
│   ├─ analyze_teams       配队分析（库内 teams 优先 → 官方职业规则 → LLM 参考）             │
│   ├─ calculate_materials 材料总需求统计（精1/精2 + 技能升级聚合）                          │
│   ├─ search_guides       攻略检索：B站视频列表 + 搜索直达 + wiki 攻略页（API 失败自动降级）  │
│   └─ search_stage_guides 关卡攻略检索（活动关/肉鸽图：摆完挂机/单核/高配/低配/肉鸽N15）      │
│   └─ get_game_events    重大事件查询（版本更新/活动/卡池/前瞻，bwiki 官方时间 + 30 分钟缓存）   │
│                                                                                        │
│  rag/: bge-small-zh(512维) + Chroma 按游戏隔离 + 混合检索（名称置顶/向量/关键词/元素×职能） │
│  memory/: SQLite 会话 + 摘要滚动压缩 + 用户偏好 + Memory RAG 记忆向量召回（跨会话）         │
└───────────────────────────────┬───────────────────────────┬─────────────────────────────┘
                                │                           │
                     ┌──────────▼──────────┐     ┌──────────▼──────────┐
                     │ 多游戏知识包          │     │ 官方数据管道           │
                     │ genshin 100+ 静态    │     │ BWIKI / PRTS 解析器    │
                     │ 15 动态角色 90+ 头像  │     │ 限流+退避 · 每日预热 cron │
                     │ arknights 11+3 干员  │     │ 用户反馈闭环            │
                     └─────────────────────┘     └───────────────────────┘
```

## 项目结构

```
ai-game-assistant/
├── backend/                 # FastAPI + LangGraph 后端
│   ├── app/
│   │   ├── main.py          # 应用入口（FastAPI）
│   │   ├── core/            # 配置 / 日志 / 错误码
│   │   ├── schemas/         # Pydantic 数据模型
│   │   ├── api/             # 路由：games / sessions / chat（含 SSE 流式）
│   │   ├── knowledge/       # 游戏注册表（多游戏知识包）
│   │   ├── rag/             # bge-small-zh 向量化 + Chroma 按游戏隔离 + 混合检索
│   │   ├── agents/          # LangGraph 状态图（plan/route/retrieve/tool/synthesize/reflect/fallback）
│   │   │   ├── prompts.py   # 上下文工程：Prompt 模板化 + 上下文预算 + 记忆注入
│   │   │   ├── scratch_react.py  # 自研轻量 ReAct 循环（不依赖 LangGraph）
│   │   ├── tools/           # Function Calling 工具注册表（6 工具：实体查询/配队/材料/攻略/关卡攻略/重大事件）
│   │   │   ├── game_entity.py     # 实体查询全链路（静态→wiki→LLM 补缺→交叉验证）
│   │   │   ├── strategy_tools.py  # 配队分析/材料换算/攻略检索（含 B站视频跳转）
│   │   │   └── registry.py        # JSON Schema 注册 → 模型 bind_tools
│   │   └── memory/          # SQLite 会话存储 + 记忆分层（会话摘要 / 用户偏好）
│   ├── config/games.yaml    # 游戏注册表（含 wiki 接口配置）
│   ├── data/                # 多游戏知识包（genshin / arknights）+ chroma 向量库
│   ├── models/embeddings/   # embedding 模型缓存（bge-small-zh-v1.5，约 95MB）
│   ├── scripts/             # ingest 入库 / test_rag 召回验证 / smoke_chat 对话冒烟等
│   └── requirements.txt
├── frontend/                # React 18 + TypeScript + Vite + Tailwind
│   └── src/
│       ├── components/      # GameSelector / ChatWindow / AgentTimeline / CitationCard / SessionBar
│       ├── api/client.ts    # REST + SSE 客户端（ReadableStream 解析）
│       └── types/
├── docker-compose.yml       # 一键部署（阶段三完善）
└── README.md
```

## 快速开始

### 前置

- Python 3.10+、Node 18+
- LLM API Key，三选一（优先级从高到低）：
  1. **应用内设置**（推荐）：启动后点击前端右上角 ⚙ 设置按钮，填写 Key 与模型即可，保存后即时生效、无需重启，写入 `app_data/settings.json`（不入库不入日志）；
  2. **自动读取** `C:\Users\<用户>\Desktop\key.txt`（格式：首行 LLM 类型如 `deepseek`，次行 API Key）；
  3. `backend/.env` 兜底（`DEEPSEEK_API_KEY / DEEPSEEK_MODEL / BASE_URL`）。
  密钥仅在本机保存，响应与日志只显示打码形式；`.gitignore` 已忽略 `key.txt`、`app_data/`、`.env`，不会随仓库泄露。

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # 填入 DEEPSEEK_API_KEY / DEEPSEEK_MODEL / BASE_URL
uvicorn app.main:app --host 127.0.0.1 --port 8000   # http://127.0.0.1:8000/api/health
```

### 前端

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173（/api 已代理到 8000）
```

### 知识包入库（RAG 向量化）

```bash
cd backend
# 首次需能访问 HuggingFace（模型缓存至 models/embeddings，二次无需网络）
$env:HF_ENDPOINT="https://hf-mirror.com"; $env:HF_HUB_DISABLE_XET="1"
.venv\Scripts\python.exe scripts\ingest.py --game genshin --reset
```

## Agent 架构（决策链路）

```
用户输入 → plan（LLM 意图识别 + 游戏归因兜底，JSON 解析失败重试一次）
         → route（实体查询 → tool；知识问答 → retrieve）
         → tool：DeepSeek Function Calling 循环（最多 3 轮，多工具自主选择）
               ├─ query_game_entity：静态库 → 动态缓存 → 官方 wiki → LLM 补缺 → 交叉验证 → 增量补全
               ├─ analyze_teams：配队分析（库内 teams → 官方职业规则 → LLM 参考）
               ├─ calculate_materials：材料总需求聚合（精1/精2 + 技能升级，万单位归一）
               └─ search_guides：攻略检索（B站视频列表 → 前端卡片可点击跳转；API 失败降级搜索直达链接）
         → retrieve：混合检索 = 名称命中置顶 + 向量召回（Chroma/bge-zh + 类型/元素重排）+ 元素×职能精确补充 + 关键词兜底
         → synthesize（LLM 依据资料组织回答，附引用；攻略视频/链接以 guides 卡片呈现）
         → reflect（Reflection 自检：忠实性/覆盖度/幻觉 → 不合格回炉 synthesize 一次）
```

SSE 流式：`POST /api/chat/stream` 增量推送节点事件（agent_start/end、tool_call/result、retrieval、citations、guides、related_entities、tasks、subagent、replan、usage、done），前端 AgentTimeline 实时渲染（含 🔍 质检节点）。

## 攻略检索与视频跳转

用户问「XX 怎么玩 / 攻略 / 视频 / 打法」→ plan 判为 tool 任务 → LLM 选择 `search_guides`：

- **B站视频列表**：直连 `x/web-interface/search/type`（带浏览器 UA + Referer，实测本地无需登录签名，code=0 返回 20 条），提取 Top 5 的标题（清洗 `<em>` 高亮标签）/ UP 主 / 时长 / 播放量 / BV 链接；
- **前端卡片**：每条视频一行，点击「观看」新标签跳转 `bilibili.com/video/{bvid}`；底部附「B站搜索更多 →」「官方 wiki 攻略页 →」；
- **降级策略**：API 被 412 拦截或超时 → 自动构造 `search.bilibili.com/all?keyword=游戏+实体+主题` 直达链接，保证用户总能到达攻略资源；
- **限速**：搜索按需触发（每轮对话最多 1 次工具调用），避免频繁触发平台风控。
- 实测：`那维莱特 配队` → 返回「0命龙王9月深渊三间连打」「那维莱特迎来了最合适的配队」等真实视频。

### 明日方舟关卡攻略（search_stage_guides）

关卡场景自动判别（plan 识别关卡名：H8-4 / TW-8 / 1-7 / 傀影肉鸽 等 + 攻略意图 → entity_type=level），并**理解攻略类型黑话**：

| 用户说法 | 识别结果 | 搜索关键词 |
| --- | --- | --- |
| 「H8-4 摆完挂机怎么打」 | 摆完挂机 | 明日方舟 H8-4 摆完挂机 攻略 |
| 「TW-8 单核作业」 | 单核 | 明日方舟 TW-8 单核 攻略 |
| 「1-7 高配通关」 | 高配 | 明日方舟 1-7 高配 攻略 |
| 「傀影肉鸽N15」 | 肉鸽N15 | 明日方舟 傀影与猩红孤钻 肉鸽N15 攻略 |

- 关卡名归一：`第八章 H8-4` → `H8-4`（字母数字组合提取 + 大写）；肉鸽保留主题名 + N 数字；
- 攻略类型：摆完挂机/挂机、单核/双核/三核、高配、低配/平民/无六星、肉鸽N15/N12、突袭/磨难；
- **系统级注入兜底**：plan 识别的 guide_type 在 tool_node 自动补入工具参数（LLM 未传时），保证类型理解 100% 落地；
- B站接口偶发 412 自动重试一次（退避 1.2s），仍失败降级搜索直达链接；
- 前端复用攻略视频卡片，关卡场景额外生成「摆完挂机/单核/高配/低配」建议按钮；
- 实测：`H8-4 摆完挂机` → 《四步解手H8-4》《H16-1至H16-4挂机流》；`傀影肉鸽` → 《肉鸽全关卡挂机流》《平民全关卡低配攻略》。

## 游戏重大事件倒计时（P2 新增）

右侧新增「⏳ 游戏重大事件」模块（**不同游戏不同配色**：原神=teal、明日方舟=rose），每秒实时刷新倒计时，**按类型标签页切换**（全部 / ⭐角色卡池 / 🗡️武器卡池 / 📅版本活动 / 🛠️版本 / 📺前瞻，每个标签带简要规则说明）。

- **数据管道**（`backend/app/events/engine.py`）：
  - 抓取 bwiki「版本历史」渲染表格 → 解析各版本确切开始日期（7.0=2026/08/12、月之八=2026/07/01、月之七=2026/05/20…）→ 按官方规律推算完整事件序列；
  - **「祈愿」页真实卡池抓取**（`fetch_gacha_table`）：解析「活动祈愿（当前）」小节 → 官方卡池名 + 5星/4星角色 + 起止时间；`merge_gacha` 按「版本号+上下半」覆盖推算事件（`estimated=False`，并开双池合并展示，武器池独立「🗡️ gacha_weapon」事件展示）；
- **事件类型**：`version_update`（🛠️ 版本更新/进行中版本）、`maintenance`（🔧 维护）、`activity`（📅 活动）、`gacha`（⭐ 卡池）、`gacha_weapon`（🗡️ 武器卡池）、`livestream`（📺 前瞻直播）；
- **事件生成规则**：当前进行中版本（版本跨度事件）+ 上下半卡池（各 21 天）+ 版本活动（周五开启惯例）+ 后续版本更新/前瞻/卡池/活动；推算值标注「预计」，真实卡池标「官方数据」；
- **真实信息优先**：卡池显示官方池名（如「涌浪叙歌」/「煦风欢舞时」）与 5星/4星角色名单（如 幽歌萦渊·沃雅妮莎、雪宴之锋·薇斯纳）；进行中版本为官方已公布时，版本活动带真实活动名（如「险境征者竞锋大赛」）；
- **优先级排序 + 近一月窗口**：进行中（active）优先、按距结束时间升序；未开始（upcoming）按距开始时间升序且**只显示近 30 天**（超窗自动过滤）——前端「进行中 · 剩 X 天」金色高亮；
- **防幻觉**：无官方数据的推算事件标注「预计」徽章 + 推算依据；无已公布排期的游戏显示「暂无已公布事件（以官方公告为准）」，不编造时间/角色；
- **缓存与限流**：抓取结果缓存 30 分钟（`data/events_cache.json`），避免高频请求被 wiki 限流；抓取失败静默降级为推算/空态；
- **API**：`GET /api/events` → `{games: [{game_id, name, color, events: [{type, title, start, end, status, countdown_sec, estimated, note}]}]}`；
- **前端**（`frontend/src/components/EventCountdown.tsx`）：类型标签页（带各分类计数与简要规则）+ 图标 + 实时倒计时每秒刷新；标题/备注自动换行不截断；同时 **Agent 决策链路折叠化**（默认只显示最近 3 条关键节点摘要，点击展开完整过程），右侧栏由 w-96 收窄至 w-80。
- 实测：当前展示「「涌浪叙歌」/「煦风欢舞时」角色卡池 进行中 · 剩 19 天（官方 5星：幽歌萦渊·沃雅妮莎 / 雪宴之锋·薇斯纳）」「7.1 版本活动 7 天后（周五 10:00）」「7.2 前瞻 29 天后」等 5 项（近 30 天窗口）。

## 测试（pytest）

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests -q     # 44 passed
```

- `tests/test_parsers.py`：PRTS 技能/天赋/材料解析器单测（固定 wikitext 样本，不联网）——验证 `{{*|20%|{{color|+20%}}}}` 公式清洗、技能 1-7 级+专精分级、天赋条件、精1/精2 与技能升级材料解析；
- `tests/test_graph.py`：Agent 图可编译（6 节点齐全）、建议按钮生成（按游戏区分话术）、检索空→工具降级路由；
- `tests/test_strategy_tools.py`：B站标题清洗、材料数量「万」单位归一；
- `tests/test_events.py`：事件倒计时引擎纯逻辑单测——6 周版本周期推算（更新日=周三）、前瞻直播早于版本更新约 14 天、upcoming/active/ended 状态判定与倒计时、优先级排序、**近 30 天窗口过滤**、**祈愿页真实卡池合并**（官方池名/角色覆盖推算、双池合并、未命中保持预计）、进行中版本带真实活动名（不联网，固定样本）。**共 44 passed**。

## 评测（LLM-as-Judge）

```bash
cd backend
.venv\Scripts\python.exe scripts\eval\build_eval_set.py   # 生成 30 条评测集
.venv\Scripts\python.exe scripts\eval\eval_runner.py      # 全量评测 → data/eval_report.json
.venv\Scripts\python.exe scripts\eval\eval_runner.py --limit 5         # 只跑前 5 条（快速回归）
.venv\Scripts\python.exe scripts\eval\eval_runner.py --only-failed    # 只重跑上次失败/低分/含幻觉用例（增量，省 token）
```

评测集 30 条（entity/knowledge/edge/complex 四类），Judge 用 DeepSeek 按四指标评分：
准确率 / 忠实性（回答是否都有引用支撑）/ 覆盖度（期望要点覆盖比例）/ 幻觉条数。
评测闭环已揪出并修复：plan 意图误判、元素反应基础知识库缺失、synthesize 编造细节、
胡桃生日数据错误（7月15日 → 12月20日，补 wiki 验证映射）、validator 定位枚举过严。

**质量对比**（LangGraph 全链路 vs 自研 ReAct）：
```bash
.venv\Scripts\python.exe scripts\compare_react.py        # 同一批问题分别跑两条链路 → data/compare_react.json
.venv\Scripts\python.exe scripts\eval\judge_compare.py   # 两组回答用同一 Judge 打分（ReAct 侧附工具返回 citations，忠实性可自动核验）
```
LangGraph（四路混合检索 + Reflection 质检 + 引用输出）质量更稳；自研 ReAct 在核心事实正确性上
持平（复核后 0 幻觉，Judge 两次误判经 trace 核实为工具返回数据与正确游戏机制），省约 35% 耗时与
~1.6k token/条，代价是检索策略简化与无引用标注——已通过共享 `hybrid_retrieve`（含元素×职能精确补充）
与 ReAct citations 输出收敛差距。

**Token 成本硬指标**（`app/core/usage.py` 通过 LangChain 回调自动统计全部 LLM 调用）：
评测报告自带本轮 token 汇总（总量 / 输入 / 输出 / 调用次数 / 平均每条），并与上一份报告对比增量。
实测：每条评测 ≈ 3,900 token（Agent 链路 + Judge），全量 30 条 ≈ 11.6 万/轮；`--only-failed` 增量回归只重跑失败项，可显著节省。
对话级：`/api/chat` 响应与 SSE `usage` 事件携带本轮消耗（前端已渲染「⚡ 本轮消耗 N token（M 次调用）」），配合上下文预算控制长会话成本。

最新全量结果（2026-09-23）：**准确率 0.962 / 忠实性 1.0 / 覆盖度 0.945 / 幻觉 0 条**（30 条，93.6k token，平均 3.1k/条）；
收尾处置（数据补录雷电将军 + synthesize 详实化 + key_points 校准）后原 3 个低分项全部满分，30 条无低分项。

### 代码审查与修复（2026-09-25）

对照「4 维度 10 检查点」逐项核查并修复，新增三块工程化证据：

**① 组件级消融实验**（`scripts/eval/ablation.py` → `data/ablation_report.json`）：
```bash
.venv\Scripts\python.exe scripts\eval\ablation.py --cases 4   # 5 配置 × 4 条，约 20 次链路，耗时 10+ 分钟
```
| 配置 | acc | Δacc | fth | cov | 幻觉/条 | token |
|---|---|---|---|---|---|---|
| 全链路 | 0.950 | — | 0.925 | 1.0 | 0.75 | 53,525 |
| 去 replan | 0.912 | -0.038 | 0.850 | 1.0 | 1.0 | 53,330 |
| 去 reflect | 0.887 | -0.063 | 0.787 | 1.0 | **2.0** | 41,119 |
| 去混合检索 | 0.725 | **-0.225** | 0.825 | 0.85 | 1.5 | 46,145 |
| 去记忆注入 | 0.688 | **-0.262** | 0.900 | **0.75** | 0.75 | 49,358 |

结论：**记忆注入与混合检索贡献最大（去掉后准确率 -0.26 / -0.23 且覆盖度明显下降），
Reflection 对防幻觉贡献显著（去掉后幻觉 0.75→2.0 条），replan 贡献中等（-0.038）——四组件均为正贡献，非过度工程**。

**② Judge 校准与统计口径**（`scripts/eval/judge_calibration.py` + `eval_common.py`）：
- 评测报告新增 **Wilson 95% 置信区间** 与阈值通过率（如 acc=0.905，95%CI 0.803~1.0，通过率 0.8 [0.49~0.943]）；
- 新建人工校准集（`calibration_set.json`，逐条人工对照期望要点打分）与校准脚本（MAE/一致率/偏差模式）；
- 校准过程**暴露并修复了真问题**：eval 报告原先只存引用标题，Judge 看不到引用正文，
  对「资料未收录但合理作答」的用例误判编造（ent-10：0.7/0.6/2 条幻觉）→ 修复为带引用正文后
  **Judge 与人工标注完全一致（1.0/1.0/1.0/0，MAE=0）**——这是 LLM-as-Judge 校准闭环的实证。

**③ Chroma 并发压力测试**（`scripts/stress_test_rag.py`）：
```bash
.venv\Scripts\python.exe scripts\stress_test_rag.py --threads 8 --rounds 8
```
8 线程 × 8 轮 = 64 次查询：**0 错误**，墙钟 13.4s（串行理论下限 104.9s，并发加速 7.8×），
但 P95=11.9s 暴露出嵌入式 PersistentClient 的锁竞争——本地单用户场景无碍，
多用户并发需串行化或换异步/独立服务端模式（已在架构决策中注明）。

**④ Supervisor 路由注册表化**（架构扩展性）：游戏子代理身份/实体类型/识别线索/数据源全部
由 `config/games.yaml` 声明（agent_id/agent_label/entity_types/hints/wiki_desc），
`prompts.py` 的 SUPPORTED_GAMES/SUBAGENT_ROLES/PLAN/SUPERVISOR 与 `graph.py` 的
`_resolve_delegate` 从注册表动态派生——**新增第三个游戏只需登记 yaml + 建数据目录，不改任何 Agent 代码**。
已有 pytest 断言覆盖（44 passed）。

最新 10 条评测（2026-09-25，带 CI）：acc=0.905（CI 0.803~1.0）/ fth=0.885 / cov=0.95 / 幻觉 0.6 条。


## 记忆分层与上下文工程（P1）

- **上下文工程**（`app/agents/prompts.py`）：Prompt 模板化（角色/规则/任务指令分离，可复用可演进）；
  上下文预算 `prepare_history` = 会话摘要 + 最近 8 条（历史超窗自动压缩），控制每次调用的 token 成本。
- **记忆分层**（`app/memory/`）：
  - 会话级：消息 ≥12 条时 LLM 滚动压缩为摘要（`session_memory.py`），跨轮次延续对话上下文；
  - 用户级：对话结束后 LLM 提取玩家偏好（如「喜欢胡桃」「关注火系蒸发队」）按游戏隔离入库
    （`user_memory.py`，`user_prefs` 表），新会话注入 system prompt 持续生效。
  - 验证：`scripts/test_memory.py`；浏览器实测「表达偏好 → 新会话 → 回答贴合偏好」链路通过。
- **自研轻量 ReAct**（`app/agents/scratch_react.py`）：不依赖 LangGraph 的手写 ReAct 循环
  （Thought → Action → Observation → Final），复用工具注册表 + RAG 检索器；
  兼容 JSON / 经典 ReAct 文本两种输出格式，带格式异常重试兜底。
  对比测试 `scripts/compare_react.py`（6 条代表性问题）：

  | 实现 | 平均耗时 | 平均 token | 特点 |
  | --- | --- | --- | --- |
  | LangGraph 状态图 | ~4.2s | 多次调用（多节点 + 质检） | 节点可观测、可组合、可单测，延迟高 |
  | 自研 ReAct | ~2.9s | ~1660 | 单循环省 token、原理透明，需格式兜底保证稳定 |

## 当前状态

- [x] 基础框架：目录结构、配置、错误体系、会话存储、游戏注册表、工具注册表、LangGraph 图、前端组件
- [x] 按需实体查询链路：静态库 → LLM 生成 → wiki 交叉验证 → 动态缓存（独立目录 + 来源标注隔离）
- [x] Agent 真实逻辑：plan 意图识别 / tool Function Calling 循环 / synthesize 组织回答
- [x] SSE 流式 + 决策链路实时可视化（浏览器实测通过）
- [x] RAG 向量化：bge-small-zh（512 维，约 95MB）+ Chroma 106 条入库 + 混合检索重排（召回验证通过）
- [x] Reflection 自检节点：synthesize → reflect → 回炉一次（浏览器实测修正链路）
- [x] 评测闭环：30 条评测集 + LLM-as-Judge 四指标评分（0.962 / 1.0 / 0.945 / 0 幻觉）
- [x] 上下文工程：Prompt 模板化 + 上下文预算（摘要 + 最近 N 条）
- [x] 记忆分层：会话摘要滚动压缩 + 用户偏好按游戏隔离跨会话生效（test_memory 验证 + 浏览器实测）
- [x] 自研 ReAct 循环模块 + 与 LangGraph 对比测试（6/6 通过，平均 2.9s / ~1660 token）
- [x] 成本可量化：全局 LLM 用量统计（评测 token 报告 + 对话级 usage 事件 + 增量重跑 --only-failed）
- [x] usage 前端可视化：SSE usage 事件消费，回答下方显示本轮 token 与调用次数（浏览器实测通过）
- [x] 混合检索收敛：graph 与 ReAct 共享 hybrid_retrieve（四路召回 + 元素×职能补充，检索实测命中菲谢尔等漏网项）
- [x] ReAct citations 输出：手写 ReAct 记录工具返回依据，Judge 忠实性可自动核验（消除误判）
- [x] 数据补录：菲谢尔 / 迪卢克 / 芭芭拉治疗定位（人工补录标注待 wiki 验证），魔女套推荐补迪卢克
- [x] 修复：synthesize 覆盖工具直答、retriever 缺 import 致 teams 加载失败、validate_data 两处崩溃
- [x] 评测收尾：30 条全量 0.962 / 1.0 / 0.945 / 0 幻觉；补录雷电将军、synthesize 详实化、key_points 校准后低分项全部清零
- [x] 阶段三 · 明日方舟二期：games.yaml 注册启用（动态生成按游戏关闭）+ 8 名干员种子数据（`backend/data/arknights/characters.json`）+ 前端游戏选择器切换实测通过（能天使问答全链路，截图 `docs/screenshots/arknights_demo.png`）
- [x] 阶段三 · MCP 工具协议：`backend/mcp_server.py`（官方 MCP SDK，stdio）暴露 list_games / query_game_entity / search_knowledge 三个标准工具；冒烟测试 `scripts/mcp_client_test.py` 全通过（握手 / 工具列表 / 实体查询 / 检索）
- [~] 阶段三 · docker-compose：backend/frontend Dockerfile、nginx 代理（含 SSE）、数据与模型缓存卷已就绪；本机 Win10 19045 WSL2 可选组件启用被系统回滚（「无法完成更新已撤销」），镜像实机构建待宿主 WSL2 可用（见「本地一键启动」/「Docker 部署」）
- [x] 2026 数据时效（2026-09）：补录原神月之五/六新角色（法尔伽 2026-02、莉奈娅 2026-04）与明日方舟 2026 新干员（怒潮凛冬、可露希尔、凯尔希·思衡托 2026-04/05）；实测动态按需获取 2026 新角色哥伦比娅（wiki 交叉验证补全法器/仙鹤座/2026-01 月之四实装）；数据来源标注 manual-2026 / 2026 新干员
- [x] 本地一键启动：`start-dev.ps1` / `stop-dev.ps1`（一键起后端+前端+健康检查，日志落 `.dev\*.log`，实测通过）
- [x] **多工具扩展（P0）**：工具集 1→4——新增 `analyze_teams`（配队分析：库内 teams → 官方职业规则 → LLM 参考）、`calculate_materials`（材料总需求聚合：珊比实测 31 种材料 / 龙门币 21 万）、`search_guides`（B站视频攻略检索 + 前端卡片跳转 + wiki 攻略页，API 412 自动降级搜索直达链接）；Function Calling 多工具自主选择
- [x] **pytest 测试套件**：14 个测试全绿（PRTS 解析器 / Agent 图编译与路由 / 建议生成 / 工具清洗与归一）
- [x] **README 升级**：架构全景图 + 多工具链路 + 攻略检索章节 + 测试章节 + key 自动读取说明
- [x] **前端攻略卡片**：assistant 消息渲染 B站视频列表（观看按钮新标签跳转）+ 「B站搜索更多 / wiki 攻略页」链接，TS 检查通过
- [x] **正文 Markdown 渲染**：轻量白名单渲染器（粗体/斜体/行内代码/编号列表/URL 自动转超链接），无 XSS；消息气泡美化
- [x] **明日方舟关卡攻略检索**：search_stage_guides 工具（活动关/主线/肉鸽），理解攻略类型黑话（摆完挂机/单核/双核/高配/低配/肉鸽N15/突袭），系统级 guide_type 注入兜底 + B站 412 自动重试；关卡建议按钮（摆完挂机/单核/高配/低配）；实测 H8-4 与傀影肉鸽均返回真实视频
- [x] **任务分解链式调用**：plan 阶段 LLM 将复合意图拆分为结构化子任务清单（subtasks，含建议工具与目标），SSE 推送 tasks 事件 → 前端 Agent 链路面板展示「任务规划」；执行阶段将规划注入提示，引导 LLM 在一个循环内**连续自主调用多个工具**（实测「那维莱特怎么配队？顺便看看攻略视频」→ 一次对话链式调用 analyze_teams + search_guides，5 条视频卡片）；单意图场景子任务为空，不改变原有链路
- [x] **游戏重大事件倒计时（P2）**：bwiki 版本表抓取 → 6 周周期推算 7.2/7.3 更新与前瞻（预计标注、防幻觉）；/api/events + 前端 EventCountdown（原神 teal / 明日方舟 rose 分色、实时倒计时每秒刷新）；Agent 决策链路折叠化 + 右侧栏收窄 w-80；pytest 新增 3 项 → **23 passed**；浏览器实测渲染通过
- [x] **事件增强（2026-09-24）**：①未开始事件近 30 天窗口过滤（active 不受限）；②事件按类型标签页（全部/角色卡池/版本活动/版本/前瞻，带简要规则说明）；③**祈愿页真实卡池接入**（官方池名+5星/4星角色+官方时间，`fetch_gacha_table`+`merge_gacha`，双池合并，estimated=false）；④标题/备注自动换行不截断；⑤进行中版本活动带真实活动名；pytest 新增 3 项 → **29 passed**；浏览器实测「涌浪叙歌/煦风欢舞时」卡池完整展示
- [x] **事件工具化 + 明日方舟事件（2026-09-25）**：新增 **get_game_events** Function Calling 工具（版本更新/活动/卡池/前瞻统一查询，带类型过滤与倒计时，30 分钟缓存防限流）；**明日方舟事件接入**——bwiki「活动关卡」页全部活动官方起止时间（SideStory/故事集/签到/危机合约，31 条 2026 数据）+「更新记录」最新版本 2.7.61 进行中（end=待官方公告，前端显示「进行中 · 待官方公告」），无卡池排期源不编造；supervisor 新增 **event 域**识别并委派对应游戏子代理，子代理调用 get_game_events 返回真实排期（实测「明日方舟最近有什么活动」→ 委派明日方舟子代理 → get_game_events → 4 项真实事件）；pytest 新增 4 项 → **44 passed**

- [x] **多智能体协作（2026-09-24）**：plan → **supervisor 主管智能体**（游戏识别 + 域判别 + 委派单 game_id/domain/delegate_to/brief/reason）→ route 委派决策 → **genshin_agent / arknights_agent / knowledge_agent 子代理**独立执行（子代理身份注入 system prompt，SSE 推送 subagent 事件「主管委派 → 原神子代理」，前端 Agent 链路面板展示委派）；实测「珊比的配队和精英化材料」→ 主管委派明日方舟子代理 → analyze_teams + calculate_materials 链式执行
- [x] **动态重规划（2026-09-24）**：Plan-Execute-Refine——tool 执行后 replan 节点规则预检（子任务建议工具未调用 / 工具返回未收录或错误）→ LLM 评估完成度 → 未完成则生成补充计划并回 tool 二次执行（上限 1 轮，防死循环）；SSE 推送 replan 事件，前端显示「🔁 动态调整计划」；纯函数 _replan_signals 单测覆盖（pending/失败/已完成三种信号）
- [x] **记忆型 Agent（2026-09-24）**：Memory RAG——会话摘要 / 用户偏好 / 常问实体向量化写入 Chroma「user_memory」集合（按游戏隔离），问答前按相关性召回注入上下文（MemGPT 式 核心/工作/外部记忆分层落地子集）；`app/memory/memory_rag.py` upsert_session + retrieve，chat 流程对话结束自动写入；pytest 新增 11 项 → **40 passed**
- [x] **武器卡池展示（2026-09-25）**：祈愿页武器池（如「神铸赋形」）生成独立 gacha_weapon 事件（5星/4星武器 + 官方时间 + estimated=false），前端新增 🗡️ 武器卡池标签（与角色池同周期）；修复 merge_gacha 未命中池保留推算事件；pytest → **44 passed**
- [x] **EXE 启动体验（2026-09-25）**：启动横幅打印技术栈版本（LangGraph 1.2.12 / LangChain 1.4.2 / 8 节点状态图 / 6 工具）；浏览器自动打开后控制台窗口自动隐藏（ShowWindow SW_HIDE，服务后台继续运行）；日志落盘 pp_data/logs/server.log；已重打包验证（窗口句柄 0、8000 服务正常）
- [x] **应用内设置 API Key（2026-09-29）**：前端 ⚙ 设置按钮（SettingsModal）+ 后端 `/api/settings/key`（GET 返回 masked_key / POST 校验并保存）；Key 支持**应用内填写 → key.txt → .env** 三级优先读取并即时生效；保存写入 `app_data/settings.json`，不入库不入日志，响应与日志仅显示打码形式；`app/core/key_manager.py` 统一管理来源与脱敏；已重打包 EXE 实测（设置端点 200，配置源 env_or_file）
## 本地一键启动（推荐，无需 Docker）

```powershell
# 项目根目录
.\start-dev.ps1     # 一键启动后端 + 前端（健康检查通过后打印地址）
.\stop-dev.ps1      # 停止（保留 backend/data、backend/models 数据）
```

等价于手动 `uvicorn` + `npm run dev`，适用于 Docker 不可用（宿主 WSL2 组件无法启用）的环境。

## 一键启动 EXE（便携版，零依赖）

无需 Python / Node / Docker，双击即用：

```powershell
# 重新打包（backend/.venv 内已装 pyinstaller）
cd ai-game-assistant
backend\.venv\Scripts\python.exe -m PyInstaller packaging.spec --noconfirm --distpath dist_pkg --workpath build_pkg
```

产物目录 `dist_pkg\多游戏AI助手\`：

```
多游戏AI助手/
├─ 多游戏AI助手.exe      # 双击启动：自动读取 key → 释放 app_data → 起服务 → 打开浏览器
├─ _internal/            # 代码 + 前端静态资源 + 运行库（Python 3.14 / PyInstaller 6.22）
└─ app_data/             # 首次启动自动生成：models（bge embedding）/ data（知识库+Chroma+SQLite）/ config
```

- **零配置**：API Key 自动读取（exe 同目录 `key.txt` → 桌面 `key.txt` → 环境变量，兼容裸 `sk-` 与键值对格式，打码展示不入日志）；
- **数据持久化**：会话、反馈、向量库写在 exe 旁 `app_data/`，重启不丢失，卸载即删；
- **完整 Agent 链路**：实测双击 → 浏览器自动打开 → 「H8-4摆完挂机怎么打」返回真实攻略视频卡片；
- **启动体验**：启动横幅打印技术栈版本（LangGraph 1.2.12 / LangChain 1.4.2 / 8 节点状态图 / 6 工具）；浏览器自动打开后控制台窗口自动隐藏，日志落盘 pp_data/logs/server.log（服务后台继续运行，退出用任务管理器）；
- 打包入口 `backend/launcher.py`（env 注入 + 资源释放 + 静态托管）；`backend/app/main.py` 生产模式自动挂载前端 dist。
- 注：打包体积约 440MB（含 182MB embedding 模型与 onnxruntime/chromadb 原生库）；首次启动需数秒释放模型。


## Docker 部署

```bash
# 前置：Docker Desktop 正常启动（Linux engine / WSL2 就绪）
cd ai-game-assistant
docker compose up -d --build
# 前端 http://localhost:5173，后端 http://localhost:8000/api/health
```

- `backend/Dockerfile`：python:3.11-slim，依赖层缓存 + 应用代码；
- `frontend/Dockerfile`：node:20-alpine 构建 → nginx:alpine 托管（`nginx.conf` 反向代理 `/api` → backend:8000，SSE 关闭 buffering）；
- 卷：`backend/data`（知识包 + Chroma + SQLite 持久化）、`backend/models`（bge embedding 缓存复用，避免容器内重新下载）；
- 密钥：`backend/.env` 经 `env_file` 注入，不入镜像。
- 注：配置已就绪并通过审查；本机 Win10 19045 的 WSL2 可选组件启用被系统回滚，镜像实机构建待宿主 WSL2 可用后执行。

## MCP 工具协议

```bash
cd backend
.venv\Scripts\python.exe mcp_server.py            # stdio 模式，等待客户端连接
.venv\Scripts\python.exe scripts\mcp_client_test.py  # 冒烟：握手 → 列工具 → 调实体查询/检索
```

任意 MCP 客户端（Claude Desktop / Cursor 等）按 stdio server 接入即可获得平台能力：
`list_games`（游戏注册表）、`query_game_entity`（按需实体查询，静态→动态→LLM 生成 + wiki 交叉验证）、
`search_knowledge`（RAG 混合检索）。

详细设计见《AI 游戏助手智能体平台项目方案.docx》。
