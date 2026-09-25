# -*- coding: utf-8 -*-
import json, sys
from pathlib import Path
root = Path("backend/data")
for g in root.iterdir():
    if not g.is_dir() or g.name == "feedback": continue
    for sub in ("", "dynamic"):
        d = g / sub
        if not d.is_dir(): continue
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                n = len(data) if isinstance(data, list) else 1
                print(f"{g.name}/{sub or '.'}/{f.name}: {n} 条")
            except Exception as e:
                print(f"{g.name}/{f.name}: 读取失败 {e}")
