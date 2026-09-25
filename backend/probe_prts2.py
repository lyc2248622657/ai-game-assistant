# -*- coding: utf-8 -*-
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from scripts.crawler.base import WikiClient, parse_template_fields
c = WikiClient("https://prts.wiki/api.php", interval=1.0)
wt = c.parse_wikitext("珊比")
# 找 干员档案/生日/性别/种族
for kw in ("干员档案", "生日", "性别", "种族", "天赋", "技能"):
    idx = wt.find(kw)
    print(f"[{kw}] 位置: {idx}")
    if idx >= 0:
        print(wt[idx:idx+300].replace(chr(10), " | "))
        print("---")
c.close()
