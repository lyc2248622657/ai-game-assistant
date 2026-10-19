"""JSON 落盘守卫：拒绝"空 / 大幅缩水"的写入，避免一次采集失败覆盖整库。

真实事故：`data/genshin/characters.json` 现在是 2 字节的 `[]`——
上游采集返回空时 `save()` 照写，把已有数据整份覆盖。

策略（宁可少写一次，不可丢一次数据）：
  - 新结果为空、而原文件非空 → 拒绝写入；
  - 新结果不足原文件 min_ratio（默认 50%）→ 拒绝写入；
  - 通过则 tmp + replace 原子落盘。
返回 True/False，调用方据此决定是否以非零退出码结束。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _count(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, list) else (1 if data else 0)
    except Exception:  # noqa: BLE001
        # 原文件损坏：视为"有数据但不可读"，此时允许覆盖（否则永远写不进去）
        return 1


def write_json_guarded(path: Path, data: Any, *, min_ratio: float = 0.5) -> bool:
    """带守卫的 JSON 写入；被拒绝时保留原文件并返回 False。"""
    path = Path(path)
    old = _count(path)
    new = len(data) if isinstance(data, list) else (1 if data else 0)
    if old > 0 and new == 0:
        logger.error("[落盘守卫] 拒绝写入 %s：本次 0 条，原文件 %d 条（疑似采集/生成失败）", path.name, old)
        return False
    if old >= 4 and new < old * min_ratio:
        logger.error(
            "[落盘守卫] 拒绝写入 %s：本次 %d 条 < 原有 %d 条的 %.0f%%（疑似不完整）",
            path.name, new, old, min_ratio * 100,
        )
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return True
