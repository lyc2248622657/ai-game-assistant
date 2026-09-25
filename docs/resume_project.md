# 简历项目条目：多游戏 AI 助手智能体平台

> 用途：简历 bullet 与面试深挖素材。所有数字均为项目内可复现事实（README / pytest / 评测报告可查证），不夸大。

## 一句话定位

基于 **LangGraph 多智能体架构** 的游戏知识问答平台：主管智能体自动识别游戏与任务域，委派子代理通过 **Function Calling** 与 **RAG** 从官方 wiki 获取真实数据并组织回答，SSE 流式呈现完整 Agent 决策链路，前端 React 交互，零依赖 EXE 一键交付。

## 简历 bullet（可直接粘贴，按岗位裁剪）

### 版本 A：技术要点版（Agent 工程师 / 大模型应用开发）

- 设计并实现 **Supervisor 主管委派式多智能体架构**（LangGraph 8 节点状态图）：一次 LLM 调用输出结构化委派单（游戏/任务域/委派对象），路由至 3 个游戏子代理独立执行，支持实体 / 知识 / 事件三类任务域自动判别；
- 基于 **Function Calling** 构建 6 个可注册业务工具（实体查询 / 配队分析 / 材料换算 / 攻略检索 / 关卡攻略 / 重大事件），实现 LLM 自主决策 → 工具执行 → 结果回填的多轮工具循环（≤3 轮）；
- 实现 **Plan-Execute-Refine 动态重规划** 与 **Reflection 自检**：规则预检 + LLM 评估驱动补充执行（上限 1 轮防死循环），质检节点校验忠实性/覆盖度/幻觉并自动回炉，评测幻觉条数为 0；
- 构建 **RAG 向量检索**（bge-small-zh 512 维 + Chroma 按游戏隔离）：混合检索 = 名称置顶 + 向量召回 + 关键词兜底 + 领域规则补充；另实现 **Memory RAG** 跨会话用户记忆召回（MemGPT 式分层记忆落地子集）；
- 设计 **官方 wiki 数据管道**（原神 bwiki / 明日方舟 bwiki）：动态缓存 + 限速防拦截 + 来源标注 + LLM 补缺交叉验证，硬数据缺失显式声明「资料未收录」，不编造；
- 全栈交付：FastAPI + SSE 流式（25 类 Agent 事件实时推送，前端时间线可视化）+ React 18 + TypeScript；pytest 44 项全绿；PyInstaller 打包零依赖 EXE（自动读 key、自动隐藏控制台、日志落盘）。

### 版本 B：成果量化版

- 3 周从零完成全栈 Agent 项目：多智能体协作 / 动态重规划 / 记忆型 Agent 三大能力全部落地；
- 30 条 LLM-as-Judge 评测：**准确率 0.962 / 忠实性 1.0 / 覆盖度 0.945 / 幻觉 0 条**，平均 3.1k token/条；
- 44 项 pytest 单测覆盖图节点 / 解析器 / 事件引擎 / 记忆 RAG；
- 覆盖双游戏（原神 / 明日方舟），真实事件数据：角色卡池（官方池名+5星/4星名单）、武器卡池、版本活动、签到活动，全部来自官方 wiki 并带倒计时；
- 对话级 token 用量可观测（SSE usage 事件 + 全局限量统计），支持增量评测回归省 token；
- 交付形态：`多游戏AI助手.exe`（28.6MB，零依赖双击运行）+ Docker Compose 配置 + MCP stdio 服务 + git 仓库（237 文件首次提交）。

## 技术栈速查（面试口径）

| 层 | 选型 | 面试一句答 |
| --- | --- | --- |
| Agent 编排 | LangGraph StateGraph | 8 节点状态机（supervisor/route/retrieve/tool/replan/synthesize/reflect/fallback），节点可单测、可观测 |
| LLM | DeepSeek（OpenAI 兼容） | langchain-openai 统一接入，Function Calling 工具循环 |
| 检索 | Chroma + bge-small-zh(512d) | onnxruntime 本地推理，按游戏隔离集合，混合检索重排 |
| 记忆 | Memory RAG + SQLite | 会话摘要滚动压缩 + 用户偏好 + 向量记忆召回（阈值 0.35） |
| 后端 | FastAPI + SSE | 25 类事件流推送 Agent 决策过程，usage 事件带 token 统计 |
| 前端 | React 18 + TS + Vite + Tailwind | 统一对话框 / 事件倒计时面板 / 决策时间线 / 攻略卡片 |
| 数据 | bwiki 官方 wiki | 版本历史 / 祈愿 / 活动关卡 / 更新记录，限速 + 30 分钟缓存 |
| 交付 | PyInstaller / Docker / MCP | EXE 零依赖；docker-compose 就绪；MCP stdio 三工具 |

## 面试深挖清单（自测用）

1. **为什么用 LangGraph 而不是纯 LangChain/手写循环？** → 状态图显式表达分支/回边，节点可独立单测与观测；对比实验：自研 ReAct 省 35% 耗时但检索策略简化、无引用标注，质检链路稳定性不足。
2. **多智能体 vs 单智能体？** → Supervisor 一次调用输出委派单，比"每个游戏一个入口"省 token 且路由可解释；子代理身份注入 system prompt 复用同一套工具/检索。
3. **怎么防幻觉？** → 三层：官方 wiki 为主（硬数据缺失明说未收录）、synthesize 只依据资料组织回答、reflect 质检（忠实性/覆盖度）不合格回炉。
4. **RAG 为什么按游戏隔离？** → 原神/方舟实体名冲突（如同名材料、技能名），隔离集合避免跨游戏污染，检索召回验证通过。
5. **动态重规划怎么防死循环？** → 二次执行上限 1 轮；规则预检（工具未调用/返回未收录）触发，非盲目重试。
6. **EXE 怎么做到零依赖？** → PyInstaller 打包 Python 3.14 + onnxruntime + chromadb + 前端 dist + 模型资源，首次启动释放 app_data；key 从本地文件自动读取不入库。
7. **事件数据怎么来的？** → bwiki 渲染页解析（api.php action=parse），活动/卡池官方起止时间；无排期源（方舟卡池/前瞻）不生成不编造，标注 estimated 区分推算。
