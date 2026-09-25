"""明日方舟 PRTS 干员增强解析：技能数值表 / 天赋 / 精英化+技能升级材料

PRTS 干员页 wikitext 结构（已实测确认）：
- 技能：`{{技能2 |技能名=… |技能类型1=自动回复 |技能类型2=手动触发
     |技能1描述=… |技能1初始=15 |技能1消耗=40 |技能1持续=30 …技能7… 技能专精1描述=…}}`
  单个模板内含 1-7 级 + 专精 1-3 的完整数值表（无需渲染 HTML）。
- 天赋：`{{天赋列表3 |天赋=第一天赋 |天赋1=名 |天赋1条件=精英1 |天赋1效果=… |天赋2=…}}`
- 材料：`{{精英化材料 |精1={{材料消耗|龙门币|3w}} …}}`、
  `{{技能升级材料 |2=… |一8=…（技能1） |二8=…（技能2）}}`
"""
from __future__ import annotations

import re

from .official_source import _clean

# ---------- PRTS 特有文本清洗 ----------
_COLOR = re.compile(r"\{\{color\|[^|]*\|([^}]*)\}\}")
_TERM = re.compile(r"\{\{术语\|[^|]*\|([^}]*)\}\}")
_AK_MARK = re.compile(r"\{\{\*\s*\|([^|}]+?)\s*\|([^|}]+?)\}\}")
_INNER = re.compile(r"\{\{[^{}]*\}\}")


def clean_ak_text(v: str) -> str:
    """清洗 PRTS 模板文本：先拆内层 {{color/术语}} → 再 {{*|a|b}}→a（b）→ 最后删残余 {{...}}"""
    v = _COLOR.sub(r"\1", v or "")
    v = _TERM.sub(r"\1", v)
    v = _AK_MARK.sub(r"\1（\2）", v)
    v = _INNER.sub("", v)
    v = v.replace("'''", "").replace("<br/>", " ").replace("<br>", " ")
    return _clean(v)


def _extract_ak_templates(wikitext: str, prefix: str) -> list[str]:
    """提取 `{{<prefix>…}}` 平衡块；prefix 后必须紧跟数字或换行
    （避免误匹配：如「技能升级材料」不以「技能+数字/换行」开头）。
    """
    out: list[str] = []
    for m in re.finditer(r"\{\{" + prefix + r"(?:[0-9]*)\s*\n", wikitext or ""):
        i = m.start()
        depth = 0
        j = i
        while j < len(wikitext):
            if wikitext.startswith("{{", j):
                depth += 1
                j += 2
            elif wikitext.startswith("}}", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        out.append(wikitext[i + 2: j - 2])
    return out


def _field(block: str, name: str, clean: bool = True) -> str:
    m = re.search(r"(?:^|\n)\|\s*" + re.escape(name) + r"\s*=\s*(.+?)\s*$", block, re.M | re.S)
    if not m:
        return ""
    return clean_ak_text(m.group(1)) if clean else m.group(1).strip()


def parse_operator_skills(wikitext: str | None) -> list[dict]:
    """技能（含 1-7 级与专精 1-3 的完整数值表）→ [{name, recovery, levels}]"""
    if not wikitext:
        return []
    out: list[dict] = []
    for block in _extract_ak_templates(wikitext, "技能"):
        name = _field(block, "技能名")
        if not name:
            continue
        recovery = _field(block, "技能类型1") or _field(block, "技能类型2")
        levels: list[dict] = []
        for lv in range(1, 8):
            desc = _field(block, f"技能{lv}描述")
            if desc:
                levels.append({
                    "level": str(lv),
                    "desc": desc,
                    "initial": _field(block, f"技能{lv}初始"),
                    "cost": _field(block, f"技能{lv}消耗"),
                    "duration": _field(block, f"技能{lv}持续"),
                })
        for i in range(1, 4):
            desc = _field(block, f"技能专精{i}描述")
            if desc:
                levels.append({
                    "level": f"专精{i}",
                    "desc": desc,
                    "initial": _field(block, f"技能专精{i}初始"),
                    "cost": _field(block, f"技能专精{i}消耗"),
                    "duration": _field(block, f"技能专精{i}持续"),
                })
        out.append({"name": name, "recovery": recovery, "levels": levels})
    return out


def parse_operator_talents(wikitext: str | None) -> list[dict]:
    """天赋 → [{name, conditions: [{condition, effect}]}]"""
    if not wikitext:
        return []
    out: list[dict] = []
    for block in _extract_ak_templates(wikitext, "天赋列表"):
        name = _field(block, "天赋1") or _field(block, "天赋")
        if not name:
            continue
        conditions: list[dict] = []
        for i in range(1, 4):
            cond = _field(block, f"天赋{i}条件")
            eff = _field(block, f"天赋{i}效果")
            if eff:
                conditions.append({"condition": cond or f"天赋{i}", "effect": eff})
        out.append({"name": name, "conditions": conditions})
    return out


_MATERIAL = re.compile(r"\{\{材料消耗\|([^|}]+)\|([^|}]+)\}\}")


def _parse_materials_str(v: str) -> list[dict]:
    items: list[dict] = []
    for m in _MATERIAL.finditer(v or ""):
        items.append({"material": m.group(1).strip(), "count": m.group(2).strip()})
    return items


def parse_materials(wikitext: str | None) -> dict:
    """精英化材料 + 技能升级材料 → {elite: [{stage, items}], skill: [{skill_index, level, items}]}"""
    result: dict = {"elite": [], "skill": []}
    if not wikitext:
        return result
    for block in _extract_ak_templates(wikitext, "精英化材料"):
        for stage in ("精1", "精2"):
            raw = _field(block, stage, clean=False)
            if raw:
                items = _parse_materials_str(raw)
                if items:
                    result["elite"].append({"stage": stage, "items": items})
    for block in _extract_ak_templates(wikitext, "技能升级材料"):
        for line in block.split("\n"):
            line = line.strip()
            m = re.match(r"\|\s*([一二三]?)(\d+)\s*=\s*(.+)$", line)
            if not m:
                continue
            skill_idx = {"": 1, "一": 1, "二": 2, "三": 3}[m.group(1)]
            items = _parse_materials_str(m.group(3))
            if items:
                result["skill"].append({
                    "skill_index": skill_idx,
                    "level": int(m.group(2)),
                    "items": items,
                })
    return result


def parse_operator_official(wikitext: str | None) -> dict:
    """明日方舟干员增强字段：skills / talents / materials"""
    return {
        "skills": parse_operator_skills(wikitext),
        "talents": parse_operator_talents(wikitext),
        "materials": parse_materials(wikitext),
    }
