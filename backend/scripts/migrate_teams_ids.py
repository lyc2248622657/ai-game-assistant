# -*- coding: utf-8 -*-
"""迁移 teams.json：成员 id 英文→中文（对齐采集器 id 体系 character_中文名）"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "data" / "genshin" / "teams.json"

# 英文别名 → wiki 页面名（中文）
MAP = {
    "hutao": "胡桃", "xingqiu": "行秋", "zhongli": "钟离", "yelan": "夜兰",
    "raiden": "雷电将军", "xiangling": "香菱", "bennett": "班尼特",
    "ayaka": "神里绫华", "kazuha": "枫原万叶", "kokomi": "珊瑚宫心海", "ganyu": "甘雨",
    "neuvillette": "那维莱特", "furina": "芙宁娜",
    "nahida": "纳西妲", "kuki": "久岐忍",
    "tartaglia": "达达利亚", "xiao": "魈", "venti": "温迪",
    "alhaitham": "艾尔海森",
}

teams = json.loads(path.read_text(encoding="utf-8"))
changed = 0
for t in teams:
    new_members = []
    for m in t["members"]:
        zh = MAP.get(m)
        if zh:
            new_members.append(f"character_{zh}")
        elif m.startswith("character_"):
            new_members.append(m)
        else:
            # 未知别名：保留但加前缀标记，便于发现
            new_members.append(f"character_{m}")
            print(f"WARN 未映射: {t['id']} -> {m}")
    if new_members != t["members"]:
        t["members"] = new_members
        changed += 1

path.write_text(json.dumps(teams, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"迁移完成：{changed} 个配队的成员 id 已对齐为 character_中文名")
