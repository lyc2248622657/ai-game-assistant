"""调试：build_entry 输入输出"""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.crawler.base import WikiClient, parse_template_fields  # noqa: E402
from scripts.crawler.run import build_entry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
cfg = yaml.safe_load((ROOT / "config" / "crawler.yaml").read_text(encoding="utf-8"))["genshin"]
print("fields.character =", cfg["fields"]["character"])

client = WikiClient(cfg["base_url"])
wt = client.parse_wikitext("丝柯克")
fields = parse_template_fields(wt)
print("fields keys sample:", {k: fields.get(k) for k in ["全名", "称号", "稀有度", "元素属性", "实装版本"]})
entry = build_entry("character", "丝柯克", fields, cfg["fields"]["character"], "test")
print("entry keys =", list(entry.keys()))
print("entry =", json.dumps(entry, ensure_ascii=False)[:800])
client.close()
