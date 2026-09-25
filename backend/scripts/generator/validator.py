# -*- coding: utf-8 -*-
"""Validator Agent：规则校验 + LLM 评审（Generator-Critic 双 Agent 中的 Critic）"""
from __future__ import annotations

import logging

from .llm import LLMClient
from .schema import ELEMENTS, FOOD_TYPES, ROLES, WEAPON_TYPES

logger = logging.getLogger("gen.validator")

# 各类型必填字段（与 validate_data.py 保持一致 + 生成阶段额外约束）
REQUIRED = {
    "character": ["id", "type", "name", "element", "weapon_type", "rarity", "role", "region", "title", "summary"],
    "weapon": ["id", "type", "name", "category", "rarity", "sub_stat", "passive"],
    "artifact": ["id", "type", "name", "two_piece", "four_piece", "rarity"],
    "food": ["id", "type", "name", "food_type", "effect", "obtain", "rarity"],
    "material": ["id", "type", "name", "category", "rarity", "usage"],
}


class Validator:
    def __init__(self, llm: LLMClient, use_llm_review: bool = False):
        self.llm = llm
        self.use_llm_review = use_llm_review

    def validate(
        self,
        entry_type: str,
        entries: list[dict],
        seed_names: list[str],
        known_ids: set[str],
    ) -> list[str]:
        """规则校验，返回错误列表（空 = 通过）"""
        errors: list[str] = []
        seed_set = set(seed_names)

        for e in entries:
            name = e.get("name", "")
            label = name or e.get("id", "?")
            # 1. 名称必须在种子清单内（防编造）
            if name and seed_set and name not in seed_set:
                errors.append(f"[{label}] 名称不在允许清单内: {name}")
            # 2. 必填字段
            for f in REQUIRED.get(entry_type, []):
                if f not in e or e[f] in ("", None):
                    errors.append(f"[{label}] 缺必填字段: {f}")
            # 3. 枚举校验
            if entry_type == "character":
                if e.get("element") not in ELEMENTS:
                    errors.append(f"[{label}] 非法元素: {e.get('element')}")
                if e.get("weapon_type") not in WEAPON_TYPES:
                    errors.append(f"[{label}] 非法武器类型: {e.get('weapon_type')}")
                if e.get("role") not in ROLES:
                    errors.append(f"[{label}] 非法定位: {e.get('role')}")
            elif entry_type == "weapon":
                if e.get("category") not in WEAPON_TYPES:
                    errors.append(f"[{label}] 非法武器类型: {e.get('category')}")
            elif entry_type == "food":
                if e.get("food_type") not in FOOD_TYPES:
                    errors.append(f"[{label}] 非法料理类型: {e.get('food_type')}")
            # 4. 稀有度范围
            r = e.get("rarity")
            if r not in (None, ""):
                try:
                    if not (1 <= int(str(r).strip("星")) <= 5):
                        errors.append(f"[{label}] 稀有度越界: {r}")
                except ValueError:
                    errors.append(f"[{label}] 稀有度非法: {r}")
            # 5. 引用存在
            for field in ("special_food", "owner_character", "prototype_food", "recommended"):
                v = e.get(field)
                if not v:
                    continue
                refs = v if isinstance(v, list) else [v]
                for ref in refs:
                    if ref and ref not in known_ids:
                        errors.append(f"[{label}] 引用不存在: {field}={ref}")

        if errors:
            # 汇总去重，控制回炉提示长度
            dedup = list(dict.fromkeys(errors))[:20]
            logger.info("[valid:%s] %d 个错误（去重后 %d）", entry_type, len(errors), len(dedup))
            return dedup

        # 可选：LLM 事实抽审（控制成本，默认关闭）
        if self.use_llm_review:
            llm_err = self._llm_review(entry_type, entries)
            if llm_err:
                logger.info("[valid:%s] LLM 评审发现 %d 条问题", entry_type, len(llm_err))
                return llm_err
        logger.info("[valid:%s] 校验通过 %d 条", entry_type, len(entries))
        return []

    def _llm_review(self, entry_type: str, entries: list[dict]) -> list[str]:
        sample = entries[:5]
        import json

        prompt = (
            f"以下是为《原神》知识库生成的 {entry_type} 条目（前5条），请检查是否存在明显的游戏事实错误"
            f"（稀有度/元素/武器类型/定位/名称张冠李戴等）。\n{json.dumps(sample, ensure_ascii=False)}"
            f"\n只输出 JSON：{{\"errors\": [\"条目名: 问题说明\", ...]}}，无问题则 errors 为空数组。"
        )
        data = self.llm.chat_json(
            "你是原神资深玩家，严格核查游戏事实。只输出 JSON。", prompt, temperature=0
        )
        return list(data.get("errors") or [])
