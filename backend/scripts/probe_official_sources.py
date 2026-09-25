# -*- coding: utf-8 -*-
"""探测米游社 wiki / BILIBILI 原神 wiki：API 可用性与技能/命座/生日字段可抓性"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def probe(base: str, page: str):
    print(f"\n===== {base} =====")
    client = httpx.Client(headers=UA, timeout=25, follow_redirects=True)
    try:
        # 1) API 可达性
        r = client.get(base, params={"action": "query", "meta": "siteinfo", "format": "json", "formatversion": "2"})
        print(f"API 状态: {r.status_code}")
        if r.status_code != 200:
            print("不可用，跳过")
            return
        data = r.json()
        gen = data.get("query", {}).get("general", {})
        print(f"站点: {gen.get('sitename')} | 生成器: {gen.get('generator')}")
        # 2) 页面 wikitext 抓取
        r2 = client.get(base, params={"action": "parse", "page": page, "prop": "wikitext", "formatversion": "2"})
        if r2.status_code != 200:
            print(f"parse 状态: {r2.status_code}")
            return
        wt = r2.json()["parse"]["wikitext"]
        print(f"wikitext 长度: {len(wt)}")
        # 3) 关键字段探测
        for kw in ["生日", "命之座", "命座", "元素战技", "元素爆发", "普通攻击", "技能", "命之座效果", "Lv1"]:
            cnt = wt.count(kw)
            if cnt:
                idx = wt.find(kw)
                print(f"  [{kw}] x{cnt}  示例: {wt[max(0,idx-30):idx+80]!r}")
        # 4) 模板名统计（角色模板/技能模板）
        tmpls = re.findall(r"\{\{\s*([^{}\n|]+)", wt)
        from collections import Counter
        top = Counter(t.strip() for t in tmpls if t.strip()).most_common(15)
        print("  模板TOP:", [t for t, _ in top])
    except Exception as e:
        print(f"异常: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    probe("https://wiki.biligame.com/ys/api.php", "胡桃")
    probe("https://wiki.miyoushe.com/ys/api.php", "胡桃")
