# -*- coding: utf-8 -*-
"""生成 Schema：各类型必填字段 / 枚举 / 生成约束（对齐 validate_data.py 与 TEMPLATE.md）"""

# 元素与武器类型枚举（原神）
ELEMENTS = ["火", "水", "雷", "冰", "风", "岩", "草"]
WEAPON_TYPES = ["单手剑", "双手剑", "长柄武器", "弓", "法器"]
ROLES = ["主C", "副C", "辅助", "治疗", "护盾辅助"]
FOOD_TYPES = ["special", "prototype"]

# 各类型生成条目数目标
TARGET_COUNTS = {
    "character": 50,
    "weapon": 40,
    "artifact": 20,
    "food": 30,
    "material": 30,
}

# 批次大小（单次 LLM 调用生成的条目数）
BATCH_SIZE = 10

# 各类型输出字段说明（生成 prompt 用）
TYPE_SCHEMA = {
    "character": {
        "desc": "角色：名称/称号/稀有度/元素/武器类型/地区/登场版本/登场日期/特殊料理/定位/标签/简介/生日/命之座/主流配队",
        "required": ["name", "title", "rarity", "element", "weapon_type", "role", "region"],
    },
    "weapon": {
        "desc": "武器：名称/类型/稀有度/主属性/副属性/被动效果/推荐角色/获取来源",
        "required": ["name", "category", "rarity", "sub_stat"],
    },
    "artifact": {
        "desc": "圣遗物套装：套装名/两件套效果/四件套效果/稀有度/推荐角色/刷取秘境",
        "required": ["name", "two_piece", "four_piece"],
    },
    "food": {
        "desc": "料理：名称/稀有度/类型(特殊或原型)/效果/获取方式/制作者(特殊料理才有)/原型料理(特殊料理才有)/食材",
        "required": ["name", "food_type", "effect", "obtain"],
    },
    "material": {
        "desc": "材料：名称/类别(货币/角色突破/怪物掉落/地区特产/料理材料)/稀有度/用途/获取来源",
        "required": ["name", "category"],
    },
}

# 字段白名单：LLM 输出只允许这些字段入库（公共字段 + 类型字段），
# 白名单外的幻觉字段（神之眼/性格/配音等未经验证信息）一律丢弃
PUBLIC_FIELDS = {"name", "rarity", "summary", "image"}
ALLOWED_FIELDS = {
    "character": PUBLIC_FIELDS | {
        "title", "element", "weapon_type", "role", "region",
        "debut_version", "debut_date", "special_food",
        "constellation", "birthday", "obtain",
        # 官方 wiki 为主要依据的增强字段（skills/constellations 以 wiki 为准，LLM 不得编造）
        "skills", "constellations", "teams",
    },
    "weapon": PUBLIC_FIELDS | {
        "category", "sub_stat", "main_stat", "passive",
        "recommended_characters", "obtain",
    },
    "artifact": PUBLIC_FIELDS | {
        "two_piece", "four_piece", "recommended_characters", "domain",
    },
    "food": PUBLIC_FIELDS | {
        "food_type", "effect", "obtain", "owner_character",
        "prototype_food", "ingredients",
    },
    "material": PUBLIC_FIELDS | {
        "category", "usage", "obtain",
    },
}
