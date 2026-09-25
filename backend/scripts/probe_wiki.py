"""探测原神 BWIKI 数据源 API 可用性与结构（一次性侦察脚本）"""
import json
import sys
import httpx

BASE = "https://wiki.biligame.com/ys/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ai-game-assistant/0.1"}


def probe(params: dict, label: str):
    try:
        r = httpx.get(BASE, params=params, headers=HEADERS, timeout=20)
        print(f"=== {label} ===")
        print("status:", r.status_code, "len:", len(r.text))
        if r.status_code == 200:
            try:
                data = r.json()
                print(json.dumps(data, ensure_ascii=False)[:800])
            except Exception:
                print(r.text[:500])
        print()
    except Exception as e:
        print(f"=== {label} FAILED: {e} ===\n")


if __name__ == "__main__":
    # 1. 站点信息
    probe({"action": "query", "meta": "siteinfo", "format": "json"}, "siteinfo")
    # 2. 语义 MediaWiki ask 查询（角色分类）
    probe(
        {"action": "ask", "query": "[[分类:角色]]|?名称|?稀有度|limit=5", "format": "json"},
        "ask 角色分类",
    )
    # 3. parse 角色页面 HTML 表格
    probe({"action": "parse", "page": "胡桃", "prop": "wikitext", "format": "json"}, "parse 胡桃 wikitext")
