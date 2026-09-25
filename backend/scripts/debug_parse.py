"""调试：parse_template_fields 对丝柯克 wikitext 的解析结果"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.crawler.base import WikiClient, parse_template_fields  # noqa: E402

client = WikiClient("https://wiki.biligame.com/ys/api.php")
wt = client.parse_wikitext("丝柯克")
print("wikitext head:")
print(wt[:800])
print("=" * 60)
fields = parse_template_fields(wt)
print("字段数:", len(fields))
for k, v in list(fields.items())[:30]:
    print(f"  {k} = {v[:50]}")
client.close()
