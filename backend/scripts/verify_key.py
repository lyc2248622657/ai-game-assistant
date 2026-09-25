# -*- coding: utf-8 -*-
"""验证 DeepSeek API key 可用性（最小请求，不打明文）"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

api_key = os.getenv("DEEPSEEK_API_KEY", "")
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
if not api_key or api_key.startswith("sk-xxxx"):
    print("ERROR: .env 中 key 无效或未配置")
    sys.exit(1)
print(f"模型: {model} | key 长度: {len(api_key)}（已打码）")

import httpx

resp = httpx.post(
    "https://api.deepseek.com/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：正常"}],
        "max_tokens": 10,
        "temperature": 0,
    },
    timeout=30,
)
print("HTTP", resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print("响应:", data["choices"][0]["message"]["content"][:50])
    print("KEY 验证通过 ✓")
else:
    print("失败:", resp.text[:300])
