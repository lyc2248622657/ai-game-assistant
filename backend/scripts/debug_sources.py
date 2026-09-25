# -*- coding: utf-8 -*-
"""调试：bilibili wiki parse 原始响应 + 探测米游社正确域名"""
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
    "Referer": "https://wiki.biligame.com/ys/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

c = httpx.Client(headers=UA, timeout=25, follow_redirects=True)

print("=== 1) bilibili parse 原始响应（前500字符）===")
try:
    r = c.get("https://wiki.biligame.com/ys/api.php",
              params={"action": "parse", "page": "胡桃", "prop": "wikitext", "formatversion": "2"})
    print("status:", r.status_code, "content-type:", r.headers.get("content-type"))
    print("body head:", r.text[:500])
except Exception as e:
    print("异常:", e)

print("\n=== 2) 米游社域名探测 ===")
for host in ["https://wiki.miyoushe.com/ys/api.php",
             "https://wiki.miyoushe.com/api.php",
             "https://bbs.miyoushe.com/ys/api.php",
             "https://www.miyoushe.com/ys/api.php"]:
    try:
        r = c.get(host, params={"action": "query", "meta": "siteinfo", "format": "json"}, timeout=12)
        print(f"{host} -> {r.status_code} {r.text[:120]}")
    except Exception as e:
        print(f"{host} -> 失败: {e}")

print("\n=== 3) bilibili 搜索页面标题（确认胡桃页面名）===")
try:
    r = c.get("https://wiki.biligame.com/ys/api.php",
              params={"action": "query", "list": "search", "srsearch": "胡桃", "srlimit": 5, "format": "json"})
    hits = r.json().get("query", {}).get("search", [])
    for h in hits:
        print(" ", h.get("title"))
except Exception as e:
    print("异常:", e)

c.close()
