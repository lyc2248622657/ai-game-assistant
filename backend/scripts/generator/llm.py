# -*- coding: utf-8 -*-
"""LLM 客户端封装：DeepSeek，强制 JSON 输出，key 从 .env 读取（不硬编码、不打印）"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger("gen.llm")

BASE = Path(__file__).resolve().parent.parent.parent


def load_config() -> dict:
    load_dotenv(BASE / ".env")
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key or key.startswith("sk-xxxx"):
        raise RuntimeError("DEEPSEEK_API_KEY 未配置（检查 backend/.env）")
    return {
        "api_key": key,
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }


class LLMClient:
    """DeepSeek Chat Completions 封装：chat() 返回文本，chat_json() 强制 JSON"""

    def __init__(self):
        cfg = load_config()
        self.api_key = cfg["api_key"]
        self.base_url = cfg["base_url"]
        self.model = cfg["model"]
        self.client = httpx.Client(timeout=120)
        self.usage_total = {"prompt_tokens": 0, "completion_tokens": 0}

    def _post(self, messages: list[dict], response_format: dict | None, temperature: float, max_tokens: int) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format:
            body["response_format"] = response_format
        for attempt in range(3):
            try:
                r = self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
                if r.status_code == 429:
                    logger.warning("限流 429，退避重试 %d/3", attempt + 1)
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                usage = data.get("usage", {})
                self.usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
                self.usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
                return data
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("LLM 请求多次失败")

    def chat(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 8192) -> str:
        data = self._post(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return data["choices"][0]["message"]["content"].strip()

    def chat_json(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 8192) -> dict:
        """强制 JSON 对象输出；若返回非 JSON 文本，尝试提取首个 {...}"""
        text = self.chat(system, user, temperature, max_tokens)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re

            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            logger.warning("LLM 未返回合法 JSON：%s", text[:200])
            return {}

    def cost_report(self) -> str:
        pt = self.usage_total["prompt_tokens"]
        ct = self.usage_total["completion_tokens"]
        # deepseek-chat 约 ¥2/M 输入、¥8/M 输出（缓存后更低），仅供参考
        est = (pt / 1_000_000) * 2 + (ct / 1_000_000) * 8
        return f"token 用量: 输入 {pt:,} / 输出 {ct:,}，估算成本 ≈ ¥{est:.3f}"
