# -*- coding: utf-8 -*-
"""PyInstaller 打包配置：多游戏 AI 助手（onedir 便携版）

产物结构：
  多游戏AI助手/
  ├─ 多游戏AI助手.exe      # 一键启动（自动读 key / 释放 app_data / 打开浏览器）
  ├─ _internal/            # 代码 + 前端 + 库文件
  └─ app_data/             # 首次启动自动生成（模型/数据库/配置，持久化）
"""
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], []

# 动态导入 / 原生扩展密集的包：全量收集
for pkg in ("chromadb", "fastembed", "onnxruntime", "tokenizers", "transformers", "huggingface_hub", "sentence_transformers"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# onnxruntime 原生库
binaries += collect_dynamic_libs("onnxruntime")

# 前端静态资源 + 默认数据（首次启动释放到 app_data）
datas += [
    ("frontend/dist", "frontend_dist"),
    ("backend/data", "data"),
    ("backend/config", "config"),
    ("backend/models", "models"),
]

# uvicorn 动态加载的模块
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio",
    "app.api.chat",
    "app.api.games",
    "app.api.knowledge",
    "app.api.sessions",
    "app.api.settings",
    "app.api.events",
    "app.core.key_manager",
    "app.agents.graph",
    "app.agents.llm",
    "app.agents.prompts",
    "app.agents.state",
    "app.rag.embedding",
    "app.rag.retriever",
    "app.rag.vectorstore",
    "app.tools.registry",
    "app.tools.strategy_tools",
    "app.tools.game_entity",
    "app.memory.session_memory",
    "app.memory.user_memory",
]

a = Analysis(
    ["backend/launcher.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tests", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="多游戏AI助手",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="多游戏AI助手",
)
