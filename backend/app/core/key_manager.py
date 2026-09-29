"""API Key 动态管理：应用内设置界面保存 → settings.json，运行时即时生效（无需重启）

设计（替代原先只读本地文件链）：
  1. 应用内设置（settings.json）为最高优先级，保存后立即生效；
  2. 环境变量 / .env（launcher 从 key.txt 链注入）作为兜底；
  3. key 只以打码形式（sk-1234****5678）出现在日志与 API 响应，绝不打印明文。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def app_data_dir() -> Path:
    """应用数据目录：PyInstaller = exe 同目录 app_data；开发 = 进程工作目录 app_data"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "app_data"
    env = os.environ.get("APP_DATA_DIR")
    if env:
        return Path(env)
    return Path.cwd() / "app_data"


SETTINGS_FILE = app_data_dir() / "settings.json"


def mask_key(key: str) -> str:
    """打码：sk-1234****5678；过短全打码"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "****" + key[-4:]


def load_saved() -> tuple[str, str] | None:
    """读取应用内设置保存的 (model, api_key)；未保存返回 None"""
    try:
        if not SETTINGS_FILE.exists():
            return None
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        key = str(data.get("api_key", "")).strip()
        if not key:
            return None
        return (str(data.get("model", "deepseek-chat")).strip(), key)
    except Exception:  # noqa: BLE001
        return None


def save(model: str, api_key: str) -> Path:
    """保存应用内设置（写 settings.json；文件路径返回供日志/前端展示）"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": (model or "deepseek-chat").strip(), "api_key": api_key.strip()}
    # 明文本地存储（单机应用），写入后立即同步给运行时 settings
    SETTINGS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _apply_to_settings(payload["model"], payload["api_key"])
    return SETTINGS_FILE


def _apply_to_settings(model: str, api_key: str) -> None:
    """同步到运行时 settings（pydantic 实例可直接赋值，后续 LLM 调用即时生效）"""
    from app.core.config import settings

    if api_key:
        settings.deepseek_api_key = api_key
    if model:
        settings.deepseek_model = model


def _key_from_file(path: Path) -> tuple[str, str] | None:
    """解析 key.txt（首行 sk-xxx；支持 KEY=xxx / MODEL=yyy 键值）"""
    try:
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:  # noqa: BLE001
        return None
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
    if key and not key.startswith("sk-xxx"):
        return (model or "deepseek-chat", key)
    return None


def resolve_runtime() -> tuple[str, str]:
    """运行时 key 解析优先级：应用内设置 > 环境变量/.env > 本地 key.txt 文件链兜底"""
    saved = load_saved()
    if saved:
        return saved
    from app.core.config import settings

    if settings.deepseek_api_key and not settings.deepseek_api_key.startswith("sk-xxx"):
        return (settings.deepseek_model, settings.deepseek_api_key)
    # 兜底文件链（不经过 launcher 直接以 uvicorn 启动时）
    base = Path.cwd()
    candidates = [
        app_data_dir() / "key.txt",
        base / "key.txt",
        Path(os.environ.get("USERPROFILE", "C:/Users/Administrator")) / "Desktop" / "key.txt",
    ]
    for c in candidates:
        hit = _key_from_file(c)
        if hit:
            return hit
    return ("", "")


def test_key(api_key: str, model: str = "deepseek-chat") -> tuple[bool, str]:
    """最小请求验证 key 可用性（不发明文到日志）"""
    import httpx

    try:
        resp = httpx.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            json={
                "model": model.strip() or "deepseek-chat",
                "messages": [{"role": "user", "content": "回复两个字：正常"}],
                "max_tokens": 10,
                "temperature": 0,
            },
            timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        return (False, f"网络错误: {e}")
    if resp.status_code == 200:
        return (True, "连接成功，Key 可用 ✓")
    body = resp.text[:200]
    if resp.status_code == 401:
        return (False, f"认证失败（{resp.status_code}）：Key 无效或已过期")
    return (False, f"请求失败（{resp.status_code}）：{body}")
