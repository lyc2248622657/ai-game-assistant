# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from scripts.crawler.base import WikiClient, parse_template_fields
c = WikiClient("https://prts.wiki/api.php", interval=1.0)
try:
    wt = c.parse_wikitext("珊比")
    print("wikitext 长度:", len(wt))
    # 打印前 2000 字符看结构
    print(wt[:2000])
except Exception as e:
    print("失败:", e)
finally:
    c.close()
