# -*- coding: utf-8 -*-
"""Generator Agent：LLM 批量生成结构化条目 JSON"""
from __future__ import annotations

import json
import logging
import re

from .llm import LLMClient

logger = logging.getLogger("gen.generator")

SYSTEM_TMPL = """你是《原神》游戏数据专家，负责生成准确、结构化的游戏知识条目。
必须严格遵循用户给定的输出 JSON 格式，只输出 JSON，不要任何解释文字。
数据必须符合游戏事实：稀有度、元素、武器类型、地区等不得编造。
JSON 格式固定为：{{"items": [条目对象, ...]}}"""


def _norm_text(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


# LLM 可能使用的别名 → 标准字段名
FIELD_ALIASES = {
    "version": "debut_version",
    "release_date": "debut_date",
    "weapon_category": "category",
    "prototype": "prototype_food",
    "owner": "owner_character",
    "desc": "summary",
    "description": "summary",
}


def normalize_entry(entry_type: str, raw: dict) -> dict:
    """把 LLM 输出规范化为标准条目（补 id/type、清洗文本、字段别名归一、白名单过滤）"""
    from .schema import ALLOWED_FIELDS

    name = _norm_text(raw.get("name"))
    if not name:
        return {}
    eid = f"{entry_type}_{name}"
    allowed = ALLOWED_FIELDS.get(entry_type, set())
    e = {
        "id": eid,
        "type": entry_type,
        "name": name,
        "image": "",
        "source": "DeepSeek LLM 生成（生成-校验双 Agent 工作流，2026-09）",
    }
    # 其余字段照搬并清洗文本，别名归一；白名单外字段（未经验证的幻觉字段）一律丢弃
    for k, v in raw.items():
        if k in ("id", "type", "name", "image", "source"):
            continue
        std_key = FIELD_ALIASES.get(k, k)
        if std_key not in allowed:
            continue
        if isinstance(v, str):
            e[std_key] = _norm_text(v)
        elif isinstance(v, list):
            e[std_key] = [_norm_text(x) for x in v if _norm_text(x)]
        elif isinstance(v, (int, float, bool)) or v is None:
            e[std_key] = v
        else:
            e[std_key] = json.dumps(v, ensure_ascii=False)
    # weapon 的武器类型字段统一为 category
    if entry_type == "weapon" and "category" not in e and "weapon_type" in e:
        e["category"] = e.pop("weapon_type")
    # character 的定位归一化：LLM 常见变体 → 规范枚举（避免 validator 反复硬错误）
    if entry_type == "character" and e.get("role"):
        from .schema import ROLES

        role = str(e["role"])
        if role not in ROLES:
            e["role"] = ROLE_ALIASES.get(role, role)
    return e


# 定位别名表：LLM 常见描述 → 规范枚举（保证知识库定位口径一致）
ROLE_ALIASES = {
    "输出": "主C",
    "站场输出": "主C",
    "近战输出": "主C",
    "爆发输出": "主C",
    "站场": "主C",
    "驻场输出": "主C",
    "副输出": "副C",
    "后台输出": "副C",
    "速切": "副C",
    "脱手输出": "副C",
    "治疗辅助": "辅助",
    "奶辅": "辅助",
    "增益辅助": "辅助",
    "增伤辅助": "辅助",
    "控制辅助": "辅助",
    "护盾": "护盾辅助",
    "盾辅": "护盾辅助",
    "治疗": "治疗",
    "奶妈": "治疗",
}


def build_user_prompt(
    entry_type: str,
    type_desc: str,
    seed_names: list[str],
    ref_map: dict[str, list[str]] | None,
    feedback: str | None,
) -> str:
    """构造生成提示：种子清单 + 可引用 id + 上次校验错误反馈（回炉）"""
    parts = [f"类型：{entry_type}（{type_desc}）"]
    parts.append(f"请生成以下 {len(seed_names)} 个条目的完整数据：{json.dumps(seed_names, ensure_ascii=False)}")
    if ref_map:
        lines = []
        for role, ids in ref_map.items():
            lines.append(f"{role}（可引用 id）：{json.dumps(ids[:60], ensure_ascii=False)}")
        parts.append("引用规范（跨条目引用必须使用这些确切 id）：\n" + "\n".join(lines))
    parts.append(
        "输出格式：{\"items\": [ {条目}, ... ]}。每个条目必须包含字段："
        + json.dumps(TYPE_REQUIRED[entry_type], ensure_ascii=False)
        + "，并尽量补充其他合理字段（如简介、标签、获取方式、细节）。"
    )
    if feedback:
        parts.append(f"【上次校验未通过，请修正】\n{feedback}")
    return "\n\n".join(parts)


TYPE_REQUIRED = {
    "character": ["name", "title", "rarity", "element", "weapon_type", "role", "region", "summary"],
    "weapon": ["name", "category", "rarity", "sub_stat", "passive", "source"],
    "artifact": ["name", "two_piece", "four_piece", "rarity"],
    "food": ["name", "rarity", "food_type", "effect", "obtain", "details"],
    "material": ["name", "category", "rarity", "usage", "source"],
}


class Generator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def generate_batch(
        self,
        entry_type: str,
        type_desc: str,
        seed_names: list[str],
        ref_map: dict[str, list[str]] | None = None,
        feedback: str | None = None,
    ) -> list[dict]:
        """生成一批条目。失败返回空列表（由编排层决定重试或跳过）"""
        prompt = build_user_prompt(entry_type, type_desc, seed_names, ref_map, feedback)
        data = self.llm.chat_json(SYSTEM_TMPL, prompt, temperature=0.4)
        items = data.get("items") or []
        entries = [normalize_entry(entry_type, it) for it in items]
        entries = [e for e in entries if e]
        logger.info("[gen:%s] 生成 %d 条（期望 %d）", entry_type, len(entries), len(seed_names))
        return entries
