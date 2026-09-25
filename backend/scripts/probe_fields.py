"""探测各分类条目数 + 页面模板字段（采集器配置依据）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.crawler.base import WikiClient, parse_template_fields  # noqa: E402

BASE = "https://wiki.biligame.com/ys/api.php"
CATS = {
    "角色": "分类:角色",
    "武器": "分类:武器",
    "圣遗物": "分类:圣遗物",
    "食物": "分类:食物",
    "材料": "分类:材料",
}
SAMPLES = {"角色": "胡桃", "武器": "护摩之杖", "圣遗物": "炽烈的炎之魔女", "食物": "幽幽大行军", "材料": "摩拉"}

client = WikiClient(BASE)
for cat, query in CATS.items():
    try:
        items = client.ask(query, limit=5)
        print(f"== {cat}: {query} → 命中 {len(items)} (分页offset存在，总数待全量) ==")
        if items:
            print("   样本:", items[0]["fulltext"], items[0].get("printouts", {}))
    except Exception as e:
        print(f"== {cat} FAILED: {e} ==")

print()
for cat, page in SAMPLES.items():
    try:
        wt = client.parse_wikitext(page)
        fields = parse_template_fields(wt)
        print(f"== {cat}「{page}」模板字段 ==")
        print("   ", list(fields.keys()))
        # 打印主模板的前几个字段值
        for k in list(fields)[:18]:
            print(f"      {k} = {fields[k][:40]}")
    except Exception as e:
        print(f"== {cat}「{page}」FAILED: {e} ==")
client.close()
