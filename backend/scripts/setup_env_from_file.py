# -*- coding: utf-8 -*-
"""安全读取 key.txt：探测格式，打码输出，绝不打印明文"""
from pathlib import Path

src = Path(r"C:\Users\Administrator\Desktop\key.txt")
if not src.exists():
    print("ERROR: key.txt 不存在")
    raise SystemExit(1)

lines = [l.strip() for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"有效行数: {len(lines)}")

key = ""
model = ""
for l in lines:
    if "=" in l:
        k, _, v = l.partition("=")
        k, v = k.strip(), v.strip()
        if "KEY" in k.upper():
            key = v
        elif "MODEL" in k.upper() or "TYPE" in k.upper():
            model = v
    else:
        # 裸值：判断是 key（sk- 开头）还是模型名
        if l.startswith("sk-"):
            key = l
        elif l and not key:
            key = l
        elif l and not model:
            model = l

if not key:
    print("ERROR: 未找到 API Key")
    raise SystemExit(1)
if not model:
    model = "deepseek-chat"  # 默认

# 打码展示
def mask(s: str) -> str:
    if len(s) <= 8:
        return s[:2] + "*" * (len(s) - 4) + s[-2:]
    return s[:6] + "*" * 8 + s[-4:]

print(f"Key 前缀: {mask(key)}  长度: {len(key)}")
print(f"模型类型: {model}")

# 写入 .env（不打印内容）
env_path = Path(__file__).resolve().parent.parent / ".env"
content = f"""# 由配置工具自动生成（2026-09-22），key 来源：本地文件，不入库不落日志
DEEPSEEK_API_KEY={key}
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL={model}

EMBEDDING_MODEL=BAAI/bge-m3
CHROMA_DIR=data/chroma
SQLITE_PATH=data/sessions.db
GAMES_CONFIG=config/games.yaml
LOG_LEVEL=INFO
"""
env_path.write_text(content, encoding="utf-8")
print(f".env 已写入: {env_path}")

# 校验 .gitignore 是否忽略 .env
gitignore = Path(__file__).resolve().parent.parent.parent / ".gitignore"
if gitignore.exists():
    gi = gitignore.read_text(encoding="utf-8")
    print(".gitignore 包含 .env:", any(x.strip() == ".env" for x in gi.splitlines()))
else:
    print("WARN: .gitignore 不存在，需手动确认 .env 不入库")
