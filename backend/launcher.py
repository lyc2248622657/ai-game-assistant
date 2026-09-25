# -*- coding: utf-8 -*-
"""一键启动入口（PyInstaller 打包 exe 用）

职责（开箱即用，零配置）：
  1. 定位运行目录（exe 所在目录；开发模式 = backend/ 上级目录）
  2. 首次启动从内置资源释放 app_data/{models,data,config}（持久化，重启不再解压）
  3. 自动读取 API Key：app_data/key.txt → exe 同目录 key.txt → 用户桌面 key.txt → 环境变量
     （兼容裸值 sk-xxx 与 LLM_TYPE/DEEPSEEK_API_KEY 键值对两种格式，不落库不入日志）
  4. 设置绝对路径环境变量后启动 uvicorn，自动打开浏览器；
     浏览器打开成功后隐藏控制台窗口（服务后台继续运行，日志落 app_data/logs/server.log）
"""
import ctypes
import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000


def _bundle_dir() -> Path:
    """内置资源目录：PyInstaller 运行时 = _MEIPASS；开发模式 = backend/"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def app_base() -> Path:
    """运行目录：exe 所在目录（frozen）；开发模式 = backend/ 上级（项目根）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ensure_app_data(base: Path) -> Path:
    """首次启动把内置默认数据（模型/数据库/配置）释放到 exe 同目录 app_data/"""
    app_data = base / "app_data"
    app_data.mkdir(parents=True, exist_ok=True)
    bundle = _bundle_dir()
    for sub in ("models", "data", "config"):
        src = bundle / sub
        dst = app_data / sub
        if src.exists() and not dst.exists():
            try:
                shutil.copytree(src, dst)
                print(f"[启动] 首次释放 {sub} → app_data/{sub}")
            except Exception as e:  # noqa: BLE001
                print(f"[警告] 释放 {sub} 失败: {e}")
    return app_data


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "****" + s[-4:]


def load_key(base: Path, app_data: Path):
    """读取 API Key：返回 (llm_type, api_key)；未找到返回 (None, None)"""
    candidates = [
        app_data / "key.txt",
        base / "key.txt",
        Path(os.environ.get("USERPROFILE", "C:/Users/Administrator")) / "Desktop" / "key.txt",
    ]
    for c in candidates:
        if not c.exists():
            continue
        try:
            lines = [l.strip() for l in c.read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception:  # noqa: BLE001
            continue
        key, model = "", ""
        for l in lines:
            if "=" in l:
                k, _, v = l.partition("=")
                k, v = k.strip(), v.strip()
                if "KEY" in k.upper():
                    key = v
                elif "MODEL" in k.upper() or "TYPE" in k.upper():
                    model = v
            else:
                if l.startswith("sk-"):
                    key = l
                elif l and not key:
                    key = l
                elif l and not model:
                    model = l
        if key:
            print(f"[启动] 已从 {c.name} 读取 API Key（{_mask(key)}）")
            return (model or "deepseek-chat", key)
    return (None, None)


def set_env_from_key(model: str | None, key: str | None, app_data: Path) -> None:
    """把 key 与路径写入环境变量（config 从环境变量读取）"""
    if key:
        os.environ["DEEPSEEK_API_KEY"] = key
        os.environ["LLM_TYPE"] = model or "deepseek-chat"
    os.environ["EMBEDDING_CACHE_DIR"] = str(app_data / "models" / "embeddings")
    os.environ["CHROMA_DIR"] = str(app_data / "data" / "chroma")
    os.environ["SQLITE_PATH"] = str(app_data / "data" / "sessions.db")
    os.environ["GAMES_CONFIG"] = str(app_data / "config" / "games.yaml")
    # key 所在目录作为静态数据兜底（gamename 等由 config 管理）
    os.environ["APP_DATA_DIR"] = str(app_data)


def redirect_logs(app_data: Path) -> None:
    """把 stdout/stderr 重定向到 app_data/logs/server.log（隐藏窗口后日志仍可查）"""
    try:
        log_dir = app_data / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "server.log"
        sys.stdout = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
        print(f"[启动] 日志落盘: {log_file}")
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 日志重定向失败: {e}")


def hide_console() -> None:
    """隐藏当前进程的控制台窗口（服务仍在后台运行，退出请用任务管理器）"""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001
        pass


def print_stack_banner() -> None:
    """启动横幅：打印核心技术栈（简历演示截图可见 LangGraph / FastAPI / 工具数）"""
    try:
        import langgraph
        import langchain
    except Exception:  # noqa: BLE001
        langgraph = langchain = None
    lg_ver = getattr(langgraph, "__version__", "?") if langgraph else "?"
    lc_ver = getattr(langchain, "__version__", "?") if langchain else "?"
    print("=" * 56)
    print("  多游戏 AI 助手智能体平台  ·  一键启动")
    print(f"  Agent 编排: LangGraph {lg_ver} + LangChain {lc_ver}（8 节点状态图）")
    print("  后端: FastAPI · SSE 流式  |  前端: React 18 + TS + Vite")
    print("  RAG: Chroma + bge-small-zh（按游戏隔离） |  Function Calling 工具 × 6")
    print("  主模型: DeepSeek（OpenAI 兼容） |  数据: bwiki 官方 wiki 交叉验证")
    print("=" * 56)


def open_browser_soon() -> None:
    """延迟打开浏览器（等服务就绪）；打开成功后隐藏控制台窗口"""
    def _do():
        time.sleep(4)
        try:
            webbrowser.open(f"http://{HOST}:{PORT}")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
        hide_console()
    threading.Thread(target=_do, daemon=True).start()


def main() -> None:
    base = app_base()
    app_data = ensure_app_data(base)
    print_stack_banner()
    model, key = load_key(base, app_data)
    set_env_from_key(model, key, app_data)
    if not key:
        print("[警告] 未找到 API Key：请在 exe 同目录或桌面放置 key.txt（首行 sk-xxx）")

    redirect_logs(app_data)

    import uvicorn

    # 直接传 app 对象（避免打包环境下 importlib 按字符串加载 "app.main" 失败）
    from app import main as app_module

    # 用绝对路径 + 无 reload 启动（打包环境不做热更新）
    print(f"[启动] 多游戏 AI 助手服务 http://{HOST}:{PORT}  （按 Ctrl+C 退出）")
    open_browser_soon()
    uvicorn.run(
        app_module.app,
        host=HOST,
        port=PORT,
        reload=False,
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
