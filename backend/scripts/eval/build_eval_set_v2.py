# -*- coding: utf-8 -*-
"""生成扩展评测集 evaluation_set_v2.json（251 条）

结构：
- numeric 题（201 条）：属性/数值型，带确定性 ground_truth，accuracy 由规则比对判定（不依赖 LLM）
    · 原神角色 133 条（星级/元素/武器类型轮换）
    · 原神生日 20 条 / 命座一命 15 条
    · 方舟干员 33 条（星级/伤害类型/职业）
- judge 题（50 条）：原 30 条原神 + 20 条方舟开放题，保留 LLM-as-Judge 评审（忠实性/覆盖度/幻觉）

用法（backend 目录）:
    .venv\\Scripts\\python.exe scripts\\eval\\build_eval_set_v2.py
"""
import json
import random
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE.parent.parent / "data"
OUT = BASE / "evaluation_set_v2.json"

random.seed(42)  # 可复现

# ---------- 1. 原神角色属性题 ----------
ch = json.loads((DATA / "genshin" / "dynamic" / "characters.json").read_text(encoding="utf-8"))
attrs = [
    ("rarity", lambda e: f"{e.get('rarity')}星" if e.get("rarity") else "", "是几星角色？"),
    ("element", lambda e: e.get("element") or "", "是什么元素？"),
    ("weapon_type", lambda e: e.get("weapon_type") or "", "使用什么类型的武器？"),
]
numeric: list[dict] = []
for i, e in enumerate(ch):
    key, getter, qs = attrs[i % 3]
    gt = getter(e)
    if not gt:
        continue
    numeric.append({
        "id": f"num-genshin-{i+1:03d}",
        "type": "numeric",
        "game_id": "genshin",
        "question": f"{e['name']}{qs}",
        "ground_truth": str(gt),
        "key_points": [e["name"], str(gt)],
    })

# ---------- 2. 原神生日题 ----------
bd = [e for e in ch if e.get("birthday")]
random.shuffle(bd)
for i, e in enumerate(bd[:20]):
    numeric.append({
        "id": f"num-genshin-bd-{i+1:02d}",
        "type": "numeric",
        "game_id": "genshin",
        "question": f"{e['name']}的生日是哪一天？",
        "ground_truth": e["birthday"],
        "key_points": [e["name"], e["birthday"]],
    })

# ---------- 3. 原神命座题 ----------
cl = [e for e in ch if e.get("constellations")]
random.shuffle(cl)
for i, e in enumerate(cl[:15]):
    name = e["constellations"][0]["name"]
    numeric.append({
        "id": f"num-genshin-c1-{i+1:02d}",
        "type": "numeric",
        "game_id": "genshin",
        "question": f"{e['name']}的第一命座叫什么？",
        "ground_truth": name,
        "key_points": [e["name"], name],
    })

# ---------- 4. 方舟干员属性题 ----------
ak = json.loads((DATA / "arknights" / "characters.json").read_text(encoding="utf-8"))
ak_attrs = [
    ("rarity", lambda e: f"{e['rarity']}星", "是几星干员？"),
    ("element", lambda e: e["element"], "造成什么类型的伤害？"),
    ("role", lambda e: e["role"], "是什么职业定位？"),
]
for i, e in enumerate(ak):
    key, getter, qs = ak_attrs[i % 3]
    gt = getter(e)
    if not gt:
        continue
    numeric.append({
        "id": f"num-arknights-{i+1:02d}",
        "type": "numeric",
        "game_id": "arknights",
        "question": f"{e['name']}{qs}",
        "ground_truth": str(gt),
        "key_points": [e["name"], str(gt)],
    })

# ---------- 5. 保留原 LLM-Judge 题（50 条） ----------
judge: list[dict] = []
for path, gid in (
    (BASE / "evaluation_set.json", "genshin"),
    (BASE / "arknights_evaluation_set.json", "arknights"),
):
    data = json.loads(path.read_text(encoding="utf-8"))
    for c in data:
        c = dict(c)
        c.setdefault("game_id", gid)
        c["type"] = c.get("type", "judge")
        judge.append(c)

cases = numeric + judge
OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")

n_numeric = len(numeric)
n_judge = len(judge)
by_game = {}
for c in cases:
    by_game[c["game_id"]] = by_game.get(c["game_id"], 0) + 1
print(f"已生成 {len(cases)} 条（numeric {n_numeric} + judge {n_judge}）→ {OUT}")
print(f"按游戏: {by_game}")
