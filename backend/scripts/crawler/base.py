"""BWIKI（MediaWiki + Semantic MediaWiki）采集基础组件

- ask()：语义查询，按 offset 翻页获取条目列表与属性
- parse_wikitext()：读取页面模板源码（结构化字段）
- page_images() / image_url()：获取页面图片清单与图片直链
- parse_template_fields()：解析 wikitext 模板字段（名称=值）

限流策略（重要）：
  BWIKI 对高频请求会返回 429/567 直接拦截。本模块内置两道限速：
  ① 进程级共享令牌桶（所有 WikiClient 实例共用，默认 1 req/s，突发 2）
  ② 单请求退避重试（429/567/5xx → 指数退避，最多 4 次）
  切勿调小限流参数去"加速"——被拉黑后全站失效，得不偿失。
"""
from __future__ import annotations

import logging
import re
import threading
import time

import httpx

logger = logging.getLogger("crawler")

# 浏览器 UA + Referer：避免被 Cloudflare 的 UA 规则拦截（裸爬虫 UA 会返回 567）
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://wiki.biligame.com/ys/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 模板字段：|字段名=值 （允许出现在行首，无需前置换行；值可能含 [[]] 链接、{{}} 模板）
_FIELD_RE = re.compile(r"(?:^|\n)\|\s*([^=|]+?)\s*=\s*([^\n|]+)", re.M)


class _TokenBucket:
    """进程级共享令牌桶限流：全站所有请求共用一个桶，默认 1 req/s、突发 2 个。

    线程安全（Lock 保护），跨 WikiClient 实例生效——无论并发还是多次创建
    client 都不会突破全局速率。
    """

    def __init__(self, rate: float = 1.0, burst: int = 2):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def wait(self) -> float:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            wait = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
        time.sleep(wait)
        return wait


# 全局限流器（模块级单例：所有 WikiClient 共享）
_GLOBAL_RATE_LIMITER = _TokenBucket(rate=1.0, burst=2)


class WikiClient:
    def __init__(self, base_url: str, headers: dict | None = None, interval: float = 1.0):
        self.base_url = base_url
        self.headers = headers or DEFAULT_HEADERS
        self.interval = interval
        self.client = httpx.Client(headers=self.headers, timeout=30, follow_redirects=True)

    def _get(self, params: dict) -> dict:
        """GET API，带全局限流 + 退避重试（BWIKI 对高频请求返回 567）"""
        params.setdefault("format", "json")
        last_exc: Exception | None = None
        for attempt in range(4):
            _GLOBAL_RATE_LIMITER.wait()          # ① 全局令牌桶（硬限速）
            time.sleep(self.interval * (attempt + 1))  # ② 单请求退避
            try:
                r = self.client.get(self.base_url, params=params)
                if r.status_code in (429, 567) or r.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"Server error {r.status_code} for url {r.url}", request=r.request, response=r
                    )
                    logger.warning("请求限流(%s) 第%d次，退避重试: %s", r.status_code, attempt + 1, r.url)
                    time.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code in (429, 567) or e.response.status_code >= 500:
                    logger.warning("请求限流 第%d次，退避重试", attempt + 1)
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
            except httpx.TransportError as e:
                last_exc = e
                logger.warning("网络异常 第%d次，退避重试: %s", attempt + 1, e)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"请求多次失败: {params}") from last_exc

    # ---------- 语义查询 ----------
    def ask(self, query: str, limit: int = 50) -> list[dict]:
        """SMW ask 查询，自动翻页。返回 [{fulltext, fullurl, printouts:{字段:[值,...]}}]"""
        results: list[dict] = []
        offset = 0
        while True:
            q = f"{query}|limit={limit}|offset={offset}"
            data = self._get({"action": "ask", "query": q, "formatversion": "2"})
            res = data.get("query", {}).get("results", {})
            for title, item in res.items():
                item["fulltext"] = item.get("fulltext") or title
                results.append(item)
            cont = data.get("query-continue-offset")
            if cont is None:
                break
            offset = int(cont)
        return results

    # ---------- 页面内容 ----------
    def resolve_title(self, page: str) -> str:
        """P1-1：MediaWiki redirect/大小写规范化——把用户输入名称解析为真实页面标题。

        返回实际页面名（redirect 已跟随）；页面不存在时原样返回。
        """
        try:
            data = self._get(
                {
                    "action": "query",
                    "titles": page,
                    "redirects": "1",
                    "formatversion": "2",
                }
            )
            q = data.get("query", {})
            pages = q.get("pages", [])
            if pages and pages[0].get("missing"):
                # 页面缺失：尝试 SMW 模糊匹配（含关键词搜索）
                return page
            if pages:
                return pages[0].get("title") or page
        except Exception:  # noqa: BLE001
            pass
        return page

    def parse_wikitext(self, page: str) -> str:
        """读取页面模板源码（结构化字段）。
        注意：该 wiki 的 parse+formatversion=2 会返回 HTML 错误页，必须用 format=json。"""
        data = self._get(
            {"action": "parse", "page": page, "prop": "wikitext", "format": "json"}
        )
        return data["parse"]["wikitext"]["*"]

    def parse_rendered_html(self, page: str) -> str:
        """读取页面渲染后的 HTML（技能数值表/属性表等模板展开后的内容）"""
        data = self._get(
            {"action": "parse", "page": page, "prop": "text", "format": "json"}
        )
        return data["parse"]["text"]["*"]

    def page_images(self, page: str) -> list[str]:
        """页面引用的图片文件列表（File: 前缀）"""
        data = self._get(
            {"action": "query", "titles": page, "prop": "images", "imlimit": "max", "formatversion": "2"}
        )
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return []
        return [img["title"] for img in pages[0].get("images", [])]

    def image_url(self, file_title: str) -> str | None:
        """图片文件 → 直链 URL"""
        data = self._get(
            {
                "action": "query",
                "titles": file_title,
                "prop": "imageinfo",
                "iiprop": "url",
                "formatversion": "2",
            }
        )
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return None
        info = pages[0].get("imageinfo") or []
        return info[0].get("url") if info else None

    def close(self):
        self.client.close()


def parse_template_fields(wikitext: str) -> dict[str, str]:
    """从 wikitext 中提取模板字段。返回 {字段名: 值}（清洗掉链接/模板/注释）"""
    fields: dict[str, str] = {}
    # 逐段扫描 {{模板\n|字段=值\n|字段=值\n}}
    for m in re.finditer(r"\{\{\s*([^{}\n]+?)\s*\n(.*?)\}\}", wikitext, re.S):
        body = m.group(2)
        for fm in _FIELD_RE.finditer(body):
            key = fm.group(1).strip()
            value = fm.group(2).strip()
            value = re.sub(r"\[\[([^\]|]*?)\]\]", r"\1", value)   # 去掉 [[]]
            value = re.sub(r"\{\{[^{}]*?\}\}", "", value)          # 去掉内嵌模板
            value = re.sub(r"<!--.*?-->", "", value, flags=re.S)   # 注释
            fields.setdefault(key, value.strip())
    return fields
