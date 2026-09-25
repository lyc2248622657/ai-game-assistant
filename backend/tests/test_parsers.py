"""PRTS 解析器单测（固定 wikitext 样本，不联网）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.crawler.arknights_source import (  # noqa: E402
    clean_ak_text,
    parse_materials,
    parse_operator_skills,
    parse_operator_talents,
)

# 珊比 wikitext 关键片段（真实 PRTS 结构样本）
SKILL_BLOCK = """技能2
|技能名=“还不走？”
|修正=还不走
|技能类型1=自动回复
|技能类型2=手动触发
|技能1描述=攻击力{{*|20%|{{color|#0098DC|+20%}}}}，防御力{{*|20%|{{color|#0098DC|+20%}}}}，同时攻击并以{{color|#0098DC|小力度}}推动所有阻挡的敌人
|技能1初始=15
|技能1消耗=40
|技能1持续=30
|技能7描述=攻击力{{*|37%|{{color|#0098DC|+37%}}}}，防御力{{*|37%|{{color|#0098DC|+37%}}}}，同时攻击并以{{color|#0098DC|小力度}}推动所有阻挡的敌人
|技能7初始=15
|技能7消耗=34
|技能7持续=30
|技能专精1描述=攻击力{{*|40%|{{color|#0098DC|+40%}}}}，防御力{{*|40%|{{color|#0098DC|+40%}}}}，同时攻击并以{{color|#0098DC|小力度}}推动所有阻挡的敌人
|技能专精1初始=15
|技能专精1消耗=33
|技能专精1持续=30
}}"""

TALENT_BLOCK = """天赋列表3
|天赋=第一天赋
|天赋1=探险理论
|天赋1条件=精英1
|天赋1效果=珊比受到的{{术语|ba.dt.element|元素损伤}}降低5%
|天赋2=探险理论
|天赋2条件=精英2
|天赋2效果=珊比受到的{{术语|ba.dt.element|元素损伤}}降低15%
}}"""

MATERIAL_BLOCK = """精英化材料
|精1={{材料消耗|龙门币|3w}} {{材料消耗|重装芯片|5}} {{材料消耗|固源岩|12}}
|精2={{材料消耗|龙门币|18w}} {{材料消耗|重装双芯片|4}} {{材料消耗|烧结核凝晶|4}}
}}"""

SKILL_UP_BLOCK = """技能升级材料
|2={{材料消耗|技巧概要·卷1|5}}
|一8={{材料消耗|技巧概要·卷3|8}} {{材料消耗|晶体电路|4}}
|二8={{材料消耗|技巧概要·卷3|8}} {{材料消耗|转质盐聚块|4}}
}}"""

FULL_WT = "==技能==\n{{" + SKILL_BLOCK + "}}\n==天赋==\n{{" + TALENT_BLOCK + "}}\n==材料==\n{{" + MATERIAL_BLOCK + "}}\n" + "{{" + SKILL_UP_BLOCK + "}}"


def test_clean_ak_text_percent():
    """{{*|20%|{{color|+20%}}}} → 20%（+20%）；{{术语}} → 中文"""
    assert clean_ak_text("攻击力{{*|20%|{{color|#0098DC|+20%}}}}") == "攻击力20%（+20%）"
    assert clean_ak_text("{{术语|ba.dt.element|元素损伤}}") == "元素损伤"


def test_parse_skills_full_levels():
    skills = parse_operator_skills(FULL_WT)
    assert len(skills) == 1
    s = skills[0]
    assert s["name"] == "“还不走？”"
    assert s["recovery"] == "自动回复"
    # 解析器保留 wikitext 中实际存在的等级字段（1级/7级/专精1…）
    levels = [l["level"] for l in s["levels"]]
    assert "1" in levels and "7" in levels and "专精1" in levels
    by_level = {l["level"]: l for l in s["levels"]}
    assert "20%（+20%）" in by_level["1"]["desc"]
    assert by_level["1"]["initial"] == "15" and by_level["1"]["cost"] == "40"
    assert "37%（+37%）" in by_level["7"]["desc"]
    assert "40%（+40%）" in by_level["专精1"]["desc"]


def test_parse_talents():
    talents = parse_operator_talents(FULL_WT)
    assert len(talents) == 1
    t = talents[0]
    assert t["name"] == "探险理论"
    assert [c["condition"] for c in t["conditions"]] == ["精英1", "精英2"]
    assert "元素损伤" in t["conditions"][0]["effect"]


def test_parse_elite_materials():
    m = parse_materials(FULL_WT)
    elite = m["elite"]
    assert len(elite) == 2
    assert elite[0]["stage"] == "精1"
    items = elite[0]["items"]
    assert {"material": "龙门币", "count": "3w"} in items
    assert {"material": "重装芯片", "count": "5"} in items


def test_parse_skill_up_materials():
    m = parse_materials(FULL_WT)
    skill = m["skill"]
    # 2 级(通用) + 技能1的8级 + 技能2的8级
    assert len(skill) == 3
    by_key = {(s["skill_index"], s["level"]): s for s in skill}
    assert any(i["material"] == "技巧概要·卷3" for i in by_key[(1, 8)]["items"])
    assert any(i["material"] == "转质盐聚块" for i in by_key[(2, 8)]["items"])
