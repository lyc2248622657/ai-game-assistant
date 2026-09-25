"""探测特殊料理表模板行结构"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.crawler.base import WikiClient, parse_template_fields  # noqa: E402

client = WikiClient("https://wiki.biligame.com/ys/api.php")
wt = client.parse_wikitext("模板:特殊料理表/行")
print("LEN:", len(wt))
print(wt[:1500])
print("---FIELDS---")
print(list(parse_template_fields(wt).items())[:20])
client.close()
