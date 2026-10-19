r"""从模型输出中抽取 JSON 对象（统一实现，替代各处贪婪正则）。

原实现用 `re.search(r"\{.*\}", text, re.S)`：遇到"两个 JSON 对象"或"JSON 后还有花括号"
（例如文案里出现 `{...}`）就会匹配到最后一个 `}`，导致 json.loads 直接失败。
这里改用 `JSONDecoder.raw_decode` 从左往右找第一个可解析对象，天然兼容：
  - ```json 代码块围栏
  - 前后夹杂解释文字
  - 多个对象（取第一个）
"""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json(text: str) -> dict | None:
    """返回第一个合法 JSON 对象；找不到返回 None。"""
    s = str(text or "").strip()
    if not s:
        return None
    # 去掉 ``` / ```json 围栏（可能出现在首尾）
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()

    decoder = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(s[i:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def extract_json_any(text: str) -> Any | None:
    """返回第一个合法 JSON 值（对象或数组）；找不到返回 None。"""
    s = str(text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch not in "{[":
            continue
        try:
            obj, _end = decoder.raw_decode(s[i:])
        except ValueError:
            continue
        return obj
    return None
