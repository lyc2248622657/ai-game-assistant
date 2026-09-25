# -*- coding: utf-8 -*-
"""原神官方信息解析器（BWIKI 原神 wiki 为主要数据依据）

角色页 wikitext 提供：生日、命之座（6 条名称+效果）、天赋技能（技能名+描述）
角色页渲染 HTML 提供：技能数值表（Lv1~Lv10 倍率等）

用法：
    from scripts.crawler.official_source import parse_character_official
    fields = parse_character_official(wikitext, html)   # 缺源传 None 即可
"""
from __future__ import annotations

import re

_TMPL_LINK = re.compile(r"\[\[([^\]|]*?)\]\]")          # [[链接|显示]] -> 显示
_INNER_TMPL = re.compile(r"\{\{[^{}]*?\}\}")             # {{模板}} 去掉
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SPACE = re.compile(r"\s+")

# 技能分类：按模板序号与解锁条件推断
_SKILL_TYPE = {
    "普通攻击": "normal",
    "元素战技": "skill",
    "元素爆发": "burst",
    "固有天赋": "passive",
    "生活天赋": "utility",
}


def _clean(v: str) -> str:
    v = _COMMENT.sub("", v or "")
    v = _TMPL_LINK.sub(lambda m: (m.group(1).split("|")[-1] if "|" in m.group(1) else m.group(1)), v)
    v = _INNER_TMPL.sub("", v)
    v = v.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    v = re.sub(r"'''", "", v)
    v = _SPACE.sub(" ", v)
    return v.strip()


def _extract_templates(wikitext: str, name: str) -> list[str]:
    """提取所有 `{{name ...}}` 模板的正文（含换行与嵌套模板的平衡块）。

    wikitext 模板可能含内嵌 {{颜色|...}} 等，用花括号计数保证完整闭合。
    """
    out: list[str] = []
    start = 0
    while True:
        i = wikitext.find("{{" + name, start)
        if i < 0:
            break
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
        out.append(wikitext[i + 2 + len(name): j - 2])
        start = j
    return out


def parse_birthday(wikitext: str | None) -> str:
    """生日：`|生日=7月15日`（角色模板/角色/信息模板内）"""
    if not wikitext:
        return ""
    m = re.search(r"(?:^|\n)\|\s*生日\s*=\s*([^\n|]+)", wikitext)
    return _clean(m.group(1)) if m else ""


def parse_constellations(wikitext: str | None) -> list[dict]:
    """命之座：`{{角色/命之座 |命之座1=名 |命之座1效果=效果 ...}}` → [{name, effect}×6]"""
    if not wikitext:
        return []
    bodies = _extract_templates(wikitext, "角色/命之座")
    if not bodies:
        return []
    body = bodies[0]
    # 逐行解析（值可含 {{颜色|...}} 内嵌模板，不能按 | 简单切分）
    names: dict[int, str] = {}
    effects: dict[int, str] = {}
    for line in body.split("\n"):
        line = line.strip()
        m = re.match(r"\|\s*命之座(\d)效果\s*=\s*(.*)$", line, re.S)
        if m:
            effects[int(m.group(1))] = _clean(m.group(2))
            continue
        m = re.match(r"\|\s*命之座(\d)\s*=\s*(.*)$", line, re.S)
        if m:
            names[int(m.group(1))] = _clean(m.group(2))
    out = []
    for i in range(1, 7):
        if i in names or i in effects:
            out.append({"index": i, "name": names.get(i, ""), "effect": effects.get(i, "")})
    return out


def parse_skills(wikitext: str | None) -> list[dict]:
    """天赋技能：`{{天赋技能|10|...|技能名=X|描述=...}}` → [{name, type, description}]

    BWIKI 模板嵌套不严格平衡（含 {{角色技能}} 数值表等），按 `{{天赋技能` 切块、
    描述取到行首 `}}` 结束，避免跨块污染。
    """
    if not wikitext:
        return []
    out: list[dict] = []
    blocks = wikitext.split("{{天赋技能")[1:]
    skill_idx = 0
    for block in blocks:
        name = ""
        nm = re.search(r"\|\s*技能名\s*=\s*([^\n|]*)", block)
        if nm:
            name = _clean(nm.group(1))
        desc = ""
        dm = re.search(r"\|\s*描述\s*=\s*(.*?)(?=\n\}\}|\n\|属性\d+|\n\{\{|\Z)", block, re.S)
        if dm:
            desc = _clean(dm.group(1))
        if not name and not desc:
            continue  # 注释/文档块，跳过
        out.append({"name": name, "type": _classify_skill(name, desc, skill_idx), "description": desc})
        skill_idx += 1
    return out


def _classify_skill(name: str, desc: str, idx: int = 0) -> str:
    """按名称特征 + 模板顺序分类：0普攻 1战技 2爆发，解锁/烹饪 → passive/utility。

    注意：desc 里的"元素爆发"等字样可能是叙述性文字（如"令附近岩元素爆发"），
    只信任技能名称中的类型词，其余按模板顺序判定。
    """
    if "解锁" in name or "解锁" in desc[:40]:
        return "passive"
    if "烹饪" in desc and "概率" in desc:
        return "utility"
    if "元素爆发" in name:
        return "burst"
    if "元素战技" in name:
        return "skill"
    if "普通攻击" in name:
        return "normal"
    # 兜底：按模板顺序（0普攻 1战技 2爆发）
    if idx == 0:
        return "normal"
    if idx == 1:
        return "skill"
    if idx == 2:
        return "burst"
    return "passive"


def parse_skill_values(html: str | None) -> list[dict]:
    """从渲染 HTML 提取技能数值表：按表格顺序返回 [{name, levels: [Lv1..]}]。

    BWIKI 技能表：`详细属性 | LV1 | ... | LV15`，数据行 `技能名 | 数值...`。
    只处理含 `详细属性/LV1` 表头的表格，只采纳数值列 ≥5 的行（避开属性表误报）。
    """
    if not html:
        return []
    tables: list[dict] = []
    for tbl in re.findall(r"<table.*?</table>", html, re.S):
        text = re.sub(r"</?(?:td|th)[^>]*>", "|", tbl)
        text = re.sub(r"</tr[^>]*>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("&#160;", " ").replace("&nbsp;", " ")
        text = re.sub(r"[ \t]+", " ", text)
        if "详细属性" not in text and "LV1" not in text:
            continue
        rows: dict[str, list[str]] = {}
        for line in text.split("\n"):
            tokens = [t.strip() for t in line.split("|") if t.strip()]
            if len(tokens) < 6:
                continue
            name = tokens[0]
            if not re.search(r"[\u4e00-\u9fff]", name):
                continue
            vals = [
                t for t in tokens[1:]
                if re.fullmatch(r"-?\d+(?:\.\d+)?%?(?:\+\d+(?:\.\d+)?%?)?", t)
            ]
            if len(vals) >= 5:
                rows[name] = vals[:15]
        if rows:
            tables.append({"name": "", "rows": rows})
    return tables


def parse_character_official(wikitext: str | None, html: str | None) -> dict:
    """解析角色官方数据（wiki 为主要依据）。返回可直接并入条目的字段字典。"""
    fields: dict = {}
    birthday = parse_birthday(wikitext)
    if birthday:
        fields["birthday"] = birthday
    cons = parse_constellations(wikitext)
    if cons:
        fields["constellations"] = cons
    skills = parse_skills(wikitext)
    if skills:
        fields["skills"] = skills
    # 数值表按序并入攻击类技能（普攻/战技/爆发：type != passive/utility）
    tables = parse_skill_values(html)
    if tables and skills:
        ti = 0
        for s in fields["skills"]:
            if s["type"] in ("passive", "utility") or ti >= len(tables):
                continue
            rows = tables[ti]["rows"]
            # 同表内近似匹配：技能名本身的行优先，其次表内与技能名相关的行
            matched = False
            for vname, vals in rows.items():
                if vname == s["name"] or vname in s["name"] or s["name"] in vname:
                    s["levels"] = vals
                    matched = True
                    break
            if not matched and rows:
                # 整表并入（如普攻表的多段伤害）
                s["levels"] = {k: v for k, v in rows.items()}
            ti += 1
    return fields
