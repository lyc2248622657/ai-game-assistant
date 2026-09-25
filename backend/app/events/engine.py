# -*- coding: utf-8 -*-
"""游戏重大事件：抓取 → 推算 → 倒计时 → API

数据源（均为公开权威渠道，带 Referer + 限速，失败静默降级不编造）：
  - 原神：bwiki「版本历史」页面（wiki.biligame.com/ys/版本历史）渲染表格
    → 各版本确切开始日期；按「每小版本 6 周、周三更新」的官方规律推算后续版本更新与前瞻直播（标注"预计"）。
    祈愿页（wiki.biligame.com/ys/祈愿）→ 当前活动祈愿真实池名/角色/时间（estimated=false 覆盖推算）。
  - 明日方舟：bwiki「活动关卡」（wiki.biligame.com/arknights/活动关卡）渲染表格
    → 全部活动（SideStory/故事集/签到/危机合约等）官方起止时间（active/upcoming，真实数据）；
    bwiki「更新记录」→ 最新版本号与开启日期（进行中版本，真实数据）。
    卡池无官方公开排期源 → 不生成、不编造。

缓存：抓取结果写入 data/events_cache.json，TTL 30 分钟（避免高频抓取被 wiki 限流）。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

BACKEND = Path(__file__).resolve().parent.parent.parent  # backend/
CACHE_FILE = BACKEND / "data" / "events_cache.json"
CACHE_TTL_SEC = 30 * 60

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 版本周期规律（bwiki「版本历史」明示）
CYCLE_DAYS = 42          # 每小版本 6 周
UPDATE_WEEKDAY = 2       # 周三更新（datetime.weekday: 2=周三）
LIVESTREAM_DAYS = 14     # 前瞻直播约在版本更新前 14 天（周五晚）
UPCOMING_WINDOW_SEC = 30 * 86400   # 未开始事件只展示近一个月

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn2int(s: str) -> int:
    return _CN_NUM.get(s, 0)


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# 抓取：bwiki 版本历史 → 版本开始日期表
# ---------------------------------------------------------------------------
def fetch_version_table(timeout: float = 15.0) -> list[dict]:
    """抓取 bwiki「版本历史」渲染表格，返回 [{version, start, activity}]（按日期升序）"""
    url = "https://wiki.biligame.com/ys/api.php"
    params = {"action": "parse", "page": "版本历史", "format": "json", "prop": "text", "disablepp": "true"}
    with httpx.Client(headers=_HEADERS, timeout=timeout, follow_redirects=True) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        html = r.json()["parse"]["text"]["*"]
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 2:
            continue
        ver = cells[0]
        m = re.search(r"(20\d\d)[/\-](\d{1,2})[/\-](\d{1,2})", cells[1] or "")
        if not m or not ver:
            continue
        try:
            start = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if ver in seen:
            continue
        seen.add(ver)
        out.append({"version": ver, "start": start, "version_name": cells[2] if len(cells) > 2 else "",
                    "activity": cells[3] if len(cells) > 3 else ""})
    out.sort(key=lambda v: v["start"])
    return out


# ---------------------------------------------------------------------------
# 抓取：bwiki「祈愿」页 → 当前活动祈愿（真实卡池角色/武器名）
# ---------------------------------------------------------------------------
def fetch_gacha_table(timeout: float = 15.0) -> list[dict]:
    """抓 bwiki「祈愿」页「活动祈愿（当前）」小节，返回真实卡池列表。

    每项：{pool_name, kind, version("7.1上半"), start, end, chars_5, chars_4, weapons_5, weapons_4}
    抓取失败返回 []（事件保持推算值，不编造）。
    """
    url = "https://wiki.biligame.com/ys/api.php"
    params = {"action": "parse", "page": "祈愿", "format": "json", "prop": "text", "disablepp": "true"}
    with httpx.Client(headers=_HEADERS, timeout=timeout, follow_redirects=True) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        html_text = r.json()["parse"]["text"]["*"]

    idx = html_text.rfind("活动祈愿（当前）")
    if idx < 0:
        return []
    seg = html_text[idx: idx + 15000]
    # 表格 → 行级纯文本（br→换行，单元格→|，折叠空格但保留换行）
    txt = re.sub(r"<br\s*/?>", "\n", seg)
    txt = re.sub(r"</?t[dh][^>]*>", "|", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    lines = [ln.strip(" |") for ln in txt.split("\n") if ln.strip(" |")]

    pools: list[dict] = []
    cur: dict | None = None
    field = None  # 当前字段名（值在后续行）
    FIELD_KEYS = {"时间", "版本", "5星角色", "4星角色", "5星武器", "4星武器"}
    for ln in lines:
        m = re.match(r"「(.+?)」\s*\d*[期-]*\d*(?:期)?(角色|武器)活动祈愿", ln)
        if m:
            cur = {"pool_name": m.group(1), "kind": "角色" if m.group(2) == "角色" else "武器",
                   "version": "", "start": "", "end": "", "chars_5": [], "chars_4": [],
                   "weapons_5": [], "weapons_4": []}
            pools.append(cur)
            field = None
            continue
        if cur is None:
            continue
        if ln.startswith("常驻祈愿"):
            break  # 活动祈愿结束，后面是常驻池，不再解析
        if ln in FIELD_KEYS:
            field = ln
            continue
        if not field or not ln:
            continue
        val = ln.strip()
        if field == "时间":
            tm = re.findall(r"20\d\d/\d{1,2}/\d{1,2} \d{1,2}:\d{2}", val)
            if len(tm) >= 2:
                cur["start"], cur["end"] = tm[0], tm[1]
        elif field == "版本":
            cur["version"] = val
        elif field == "5星角色":
            cur["chars_5"].append(val)
        elif field == "4星角色":
            cur["chars_4"].append(val)
        elif field == "5星武器":
            cur["weapons_5"].append(val)
        elif field == "4星武器":
            cur["weapons_4"].append(val)
    return [p for p in pools if p["start"]]


def _norm_pool_chars(chars: list[str]) -> list[str]:
    """清洗角色/武器名：去「」与 (元素) 后缀，保留可读名"""
    out = []
    for c in chars:
        c = re.sub(r"^「|」$", "", c or "").strip()
        c = re.sub(r"\([^)]*\)$", "", c).strip()
        if c and c not in out:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# 抓取：明日方舟 bwiki「活动关卡」→ 全部活动官方起止时间
# ---------------------------------------------------------------------------
def _parse_ak_time(s: str) -> datetime | None:
    """'2026年09月28日 04:00' / '2026年3月14日 16:00' → datetime"""
    m = re.search(r"(20\d\d)年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", s or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)))
    except ValueError:
        return None


def fetch_ak_activities(timeout: float = 15.0) -> list[dict]:
    """抓 bwiki「活动关卡」渲染表格，返回 [{name, start, end, kind}]（仅 2026 及以后，按开始升序）。

    表格行形如「活动名 | 2026年09月28日 04:00 - 2026年10月08日 03:59 | …」。
    抓取失败返回 []（不编造）。
    """
    url = "https://wiki.biligame.com/arknights/api.php"
    params = {"action": "parse", "page": "活动关卡", "format": "json", "prop": "text", "disablepp": "true"}
    with httpx.Client(headers=_HEADERS, timeout=timeout, follow_redirects=True) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        html = r.json()["parse"]["text"]["*"]
    out: list[dict] = []
    seen: set[str] = set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 2:
            continue
        name = cells[0].strip("「」")
        m = re.search(r"(20\d\d年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})\s*-\s*(20\d\d年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})",
                      cells[1] or "")
        if not m or not name:
            continue
        start, end = _parse_ak_time(m.group(1)), _parse_ak_time(m.group(2))
        if not start or not end or start.year < 2026:
            continue
        if (name, start) in seen:
            continue
        seen.add((name, start))
        kind = "activity"
        if "复刻" in name:
            kind = "rerun"
        elif "签到" in name or "登录" in name:
            kind = "signin"
        elif "SideStory" in name:
            kind = "sidesstory"
        elif "故事集" in name:
            kind = "vignette"
        elif "危机合约" in name:
            kind = "cc"
        out.append({"name": name, "start": start, "end": end, "kind": kind})
    out.sort(key=lambda a: a["start"])
    return out


# ---------------------------------------------------------------------------
# 抓取：明日方舟 bwiki「更新记录」→ 最新版本号与开启日期
# ---------------------------------------------------------------------------
def fetch_ak_versions(timeout: float = 15.0) -> list[dict]:
    """抓 bwiki「更新记录」，返回 [{version, date, note}]（仅 2026 及以后，按日期升序）。

    段落形如「<p><b>2.7.61</b> ... 2026-07-31<br />- 2026「夏日嘉年华」限时活动开启 …」。
    抓取失败返回 []（不编造）。
    """
    url = "https://wiki.biligame.com/arknights/api.php"
    params = {"action": "parse", "page": "更新记录", "format": "json", "prop": "text", "disablepp": "true"}
    with httpx.Client(headers=_HEADERS, timeout=timeout, follow_redirects=True) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        html = r.json()["parse"]["text"]["*"]
    out: list[dict] = []
    pat = re.compile(r"<p><b>([\d.]+)</b>(?:&nbsp;|&#160;|\s)*(\d{4}-\d{2}-\d{2})\s*<br\s*/?>(.*?)</p>", re.S)
    for m in pat.finditer(html):
        ver, date, body = m.group(1), m.group(2), re.sub(r"<[^>]+>", " ", m.group(3))
        body = re.sub(r"\s+", " ", body).strip()
        if date < "2026-01-01":
            continue
        out.append({"version": ver, "date": date, "note": body[:120]})
    out.sort(key=lambda v: v["date"])
    return out


# ---------------------------------------------------------------------------
# 组合：明日方舟事件（真实数据，无卡池排期 → 不编造）
# ---------------------------------------------------------------------------
def derive_ak_events(activities: list[dict], versions: list[dict], now: datetime | None = None) -> list[dict]:
    """组合明日方舟事件：
    - 进行中版本（最新「更新记录」版本号，start 真实、end 待官方公告 → None）
    - 全部活动（SideStory/故事集/签到/危机合约等，官方起止时间，estimated=False）
    - 不生成卡池事件（无官方公开排期源，防幻觉）
    """
    now = now or datetime.now()
    events: list[dict] = []

    def _add(type_, title, start, end, note, estimated=False):
        events.append({
            "type": type_, "title": title,
            "start": _fmt_dt(start), "end": _fmt_dt(end) if end else None,
            "estimated": estimated, "note": note,
        })

    if versions:
        latest = versions[-1]
        start = datetime.strptime(latest["date"], "%Y-%m-%d").replace(hour=4)
        note = latest["note"][:60] or "最新版本更新记录"
        _add("version_update", f"版本 {latest['version']} 进行中（最新版本）", start, None,
             f"{note} · 下版本时间待官方公告")

    for a in activities:
        _add("activity", a["name"], a["start"], a["end"],
             f"官方起止时间（bwiki 活动关卡）", estimated=False)
    events.sort(key=lambda e: e["start"])
    return events


# ---------------------------------------------------------------------------
# 推算：最新版本 → 进行中版本 / 卡池 / 版本活动 / 更新 / 前瞻
# ---------------------------------------------------------------------------
def derive_upcoming(version_table: list[dict], horizon: int = 3, now: datetime | None = None) -> list[dict]:
    """基于最新已公布版本开始日期 + 官方周期规律，生成完整事件序列（标注 estimated）：
    - 当前进行中版本（版本跨度事件，含上下半卡池与版本活动）
    - 后续版本：更新维护 / 前瞻直播 / 上下半卡池 / 版本活动
    """
    if not version_table:
        return []
    latest = version_table[-1]  # 最新已公布版本
    base = latest["start"]
    # 版本名推算：数字版本（7.0 → 7.1）；"月之X"系列则退化为最新版本+序号
    ver_label_base = latest["version"]
    m = re.match(r"^(\d+)\.(\d+)$", ver_label_base)
    base_num = float(ver_label_base) if m else 0.0

    def _label(i: int) -> str:
        if base_num:
            return f"{base_num + i / 10:.1f}"
        return f"{ver_label_base}+{i}"

    def _friday(dt: datetime, hour: int = 10) -> datetime:
        """对齐到最近的周五（原神活动/前瞻惯例开启日）"""
        dt += timedelta(days=(4 - dt.weekday()) % 7)
        return dt.replace(hour=hour, minute=0, second=0)

    def _wednesday(dt: datetime, hour: int = 6) -> datetime:
        dt += timedelta(days=(UPDATE_WEEKDAY - dt.weekday()) % 7)
        return dt.replace(hour=hour, minute=0, second=0)

    # 各版本更新日（i=1..horizon，6 周间隔，对齐周三）
    update_days = [_wednesday(base + timedelta(days=CYCLE_DAYS * i)) for i in range(1, horizon + 1)]

    now = now or datetime.now()
    # 当前进行中版本窗口：最新已公布版本（start 真实）；若其推算结束日已过，
    # 则窗口顺延为推算的下一版本（标注预计）——保证始终存在"进行中"事件
    if update_days[0] > now:
        cur = {"label": ver_label_base, "start": base, "end": update_days[0], "start_est": False}
    elif len(update_days) > 1:
        cur = {"label": _label(1), "start": update_days[0], "end": update_days[1], "start_est": True}
    else:
        cur = {"label": _label(1), "start": update_days[0],
               "end": update_days[0] + timedelta(days=CYCLE_DAYS), "start_est": True}

    events: list[dict] = []
    half = timedelta(days=CYCLE_DAYS // 2)

    def _add(type_, title, start, end, note, estimated=True):
        events.append({
            "type": type_, "title": title,
            "start": _fmt_dt(start), "end": _fmt_dt(end),
            "estimated": estimated, "note": note,
        })

    # ① 当前版本进行中（版本跨度事件）+ 上下半卡池 + 版本活动
    ver_note = "按 6 周版本周期规律推算" if cur["start_est"] else "官方版本周期"
    if not cur["start_est"] and latest.get("version_name"):
        ver_note = f"版本主题「{latest['version_name']}」 · 官方版本周期"
    _add("version_update", f"版本 {cur['label']} 进行中" + ("（预计）" if cur["start_est"] else ""),
         cur["start"], cur["end"], ver_note)
    _add("gacha", f"版本 {cur['label']} 上半卡池（预计）", cur["start"], cur["start"] + half,
         "按版本上下半各 21 天规律推算，角色以官方公告为准")
    _add("gacha", f"版本 {cur['label']} 下半卡池（预计）", cur["start"] + half, cur["end"],
         "按版本上下半各 21 天规律推算，角色以官方公告为准")
    act_title = f"版本 {cur['label']} 版本活动（预计）"
    act_note = "按版本活动周五开启惯例推算，以官方公告为准"
    if not cur["start_est"] and latest.get("activity"):
        act_title = f"版本 {cur['label']} 版本活动「{latest['activity']}」"
        act_note = "活动名来自 bwiki 版本历史 · 时间按周五开启惯例推算"
    _add("activity", act_title,
         _friday(cur["start"] + timedelta(days=3)), cur["start"] + timedelta(days=28), act_note)

    # ② 后续版本：更新维护 / 前瞻 / 上下半卡池 / 版本活动
    # （cur 已顺延为推算的下一版本时，跳过 i=1 避免重复生成）
    start_i = 2 if cur["start_est"] else 1
    for i in range(start_i, horizon + 1):
        upd = update_days[i - 1]
        label = _label(i)
        _add("version_update", f"版本 {label} 更新（预计）", upd.replace(hour=6), upd.replace(hour=11),
             "按 6 周版本周期规律推算")
        ls = _friday(upd - timedelta(days=LIVESTREAM_DAYS), hour=20)
        _add("livestream", f"版本 {label} 前瞻直播（预计）", ls, ls + timedelta(hours=2),
             "按版本更新前约 2 周推算")
        _add("gacha", f"版本 {label} 上半卡池（预计）", upd, upd + half,
             "按版本上下半各 21 天规律推算，角色以官方公告为准")
        _add("gacha", f"版本 {label} 下半卡池（预计）", upd + half, upd + timedelta(days=CYCLE_DAYS),
             "按版本上下半各 21 天规律推算，角色以官方公告为准")
        _add("activity", f"版本 {label} 版本活动（预计）", _friday(upd + timedelta(days=3)), upd + timedelta(days=28),
             "按版本活动周五开启惯例推算，以官方公告为准")
    return events


# ---------------------------------------------------------------------------
# 状态与倒计时
# ---------------------------------------------------------------------------
def _status(now: datetime, start: datetime, end: datetime | None):
    if end and now >= end:
        return "ended"
    if now >= start:
        return "active"
    return "upcoming"


def merge_gacha(events: list[dict], pools: list[dict]) -> list[dict]:
    """用「祈愿」页真实卡池覆盖推算的卡池事件（匹配版本号 + 上下半）。

    命中规则：pool["version"] 形如 "7.1上半/7.1下半"，事件 title 含 "版本 7.1 上半/下半"。
    角色池命中后：title 换为卡池名（如「涌浪叙歌」），note 填 5星/4星角色，estimated=False，
    时间以官方为准；武器池（kind=武器，如「神铸赋形」）生成独立的 gacha_weapon 事件。
    未命中保持推算值（预计）。
    """
    by_key: dict[str, dict[str, list[dict]]] = {}
    for p in pools:
        v = re.match(r"^(\d+\.\d+)(上半|下半)$", p.get("version", "") or "")
        if not v or p["kind"] not in ("角色", "武器"):
            continue
        k = f"{v.group(1)}|{v.group(2)}"
        by_key.setdefault(k, {"角色": [], "武器": []})[p["kind"]].append(p)

    out = []
    for e in events:
        if e["type"] != "gacha":
            out.append(e)
            continue
        m = re.match(r"版本 (\d+\.\d+) (上半|下半)卡池", e["title"])
        if not m:
            out.append(e)
            continue
        key = f"{m.group(1)}|{m.group(2)}"
        pools_hit = by_key.get(key, {})
        if not pools_hit:
            out.append(e)
            continue
        char_pools = pools_hit.get("角色", [])
        if char_pools:
            # 同一版本上下半可能有多个并开卡池（如双 5 星池），合并展示
            parts = []
            for p in char_pools:
                chars5 = _norm_pool_chars(p["chars_5"])
                chars4 = _norm_pool_chars(p["chars_4"])
                s = f"「{p['pool_name']}」5星：{'、'.join(chars5) or '未收录'}"
                if chars4:
                    s += f" · 4星：{'、'.join(chars4)}"
                parts.append(s)
            ce = dict(e)
            names = " / ".join(f"「{p['pool_name']}」" for p in char_pools)
            ce["title"] = f"{names}角色卡池"
            ce["note"] = "；".join(parts) + "（官方数据）"
            ce["estimated"] = False
            # 官方时间格式 2026/09/23 06:00 → ISO
            ce["start"] = _fmt_dt(datetime.strptime(char_pools[0]["start"], "%Y/%m/%d %H:%M"))
            ce["end"] = _fmt_dt(datetime.strptime(char_pools[0]["end"], "%Y/%m/%d %H:%M"))
            out.append(ce)
        # 武器卡池独立事件（同周期，单独标签展示）
        weapon_pools = pools_hit.get("武器", [])
        if weapon_pools:
            parts = []
            for p in weapon_pools:
                w5 = _norm_pool_chars(p["weapons_5"])
                w4 = _norm_pool_chars(p["weapons_4"])
                s = f"「{p['pool_name']}」5星：{'、'.join(w5) or '未收录'}"
                if w4:
                    s += f" · 4星：{'、'.join(w4)}"
                parts.append(s)
            we = dict(e)
            w_names = " / ".join(f"「{p['pool_name']}」" for p in weapon_pools)
            we["type"] = "gacha_weapon"
            we["title"] = f"{w_names}武器卡池"
            we["note"] = "；".join(parts) + "（官方数据）"
            we["estimated"] = False
            we["start"] = _fmt_dt(datetime.strptime(weapon_pools[0]["start"], "%Y/%m/%d %H:%M"))
            we["end"] = _fmt_dt(datetime.strptime(weapon_pools[0]["end"], "%Y/%m/%d %H:%M"))
            out.append(we)
    return out


def attach_countdown(events: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    out = []
    for e in events:
        start = datetime.fromisoformat(e["start"])
        end = datetime.fromisoformat(e["end"]) if e.get("end") else None
        status = _status(now, start, end)
        if status == "ended":
            continue  # 已结束不展示
        e = dict(e)
        e["status"] = status
        # 进行中且无官方结束时间（如明日方舟当前版本）→ countdown_sec=None（前端显示"进行中"）
        if status == "active" and end is None:
            e["countdown_sec"] = None
        else:
            e["countdown_sec"] = int(((end if status == "active" else start) - now).total_seconds())
        # 未开始事件只显示近一个月（进行中事件不受限）
        if status == "upcoming" and e["countdown_sec"] > UPCOMING_WINDOW_SEC:
            continue
        out.append(e)
    # 优先级排序：进行中(active)优先且按距结束时间升序；即将开启(upcoming)按距开始时间升序
    # 无结束时间的 active 排在最前（长期进行中版本）
    out.sort(key=lambda e: (
        0 if e["status"] == "active" and e.get("countdown_sec") is None else
        (0 if e["status"] == "active" else 1),
        e["countdown_sec"] if e["countdown_sec"] is not None else 0,
    ))
    return out


# ---------------------------------------------------------------------------
# 汇总入口（带缓存）
# ---------------------------------------------------------------------------
GAMES = [
    {
        "game_id": "genshin",
        "name": "原神",
        "color": "teal",
        "source_url": "https://wiki.biligame.com/ys/版本历史",
    },
    {
        "game_id": "arknights",
        "name": "明日方舟",
        "color": "rose",
        "source_url": "https://wiki.biligame.com/arknights/活动关卡",
    },
]


def _load_cache() -> dict | None:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < CACHE_TTL_SEC:
                return data
    except Exception:  # noqa: BLE001
        pass
    return None


def _save_cache(payload: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps({"ts": time.time(), **payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("事件缓存写入失败: %s", e)


def build_events(force: bool = False) -> dict:
    """构建事件响应：缓存命中直接返回；否则抓取+推算"""
    cached = None if force else _load_cache()
    if cached:
        return cached.get("games", [])

    games_out: list[dict] = []
    now = datetime.now()

    # 原神：bwiki 版本表 → 推算；祈愿页 → 真实卡池角色/活动名覆盖
    try:
        table = fetch_version_table()
        events = derive_upcoming(table, horizon=3)
        try:
            pools = fetch_gacha_table()
            if pools:
                events = merge_gacha(events, pools)
                logger.info("祈愿页真实卡池覆盖 %d 个卡池事件", len(pools))
        except Exception as e:  # noqa: BLE001
            logger.warning("祈愿页抓取失败（保持推算卡池）: %s", e)
        games_out.append({
            "game_id": "genshin",
            "name": "原神",
            "color": "teal",
            "source_url": GAMES[0]["source_url"],
            "events": attach_countdown(events, now),
        })
        logger.info("原神事件抓取成功: %d 个", len(events))
    except Exception as e:  # noqa: BLE001
        logger.warning("原神事件抓取失败（降级空态）: %s", e)
        games_out.append({"game_id": "genshin", "name": "原神", "color": "teal",
                          "source_url": GAMES[0]["source_url"], "events": []})

    # 明日方舟：bwiki「活动关卡」真实活动时间表 + 「更新记录」最新版本
    try:
        ak_acts = fetch_ak_activities()
        ak_vers = fetch_ak_versions()
        ak_events = derive_ak_events(ak_acts, ak_vers, now)
        games_out.append({
            "game_id": "arknights",
            "name": "明日方舟",
            "color": "rose",
            "source_url": GAMES[1]["source_url"],
            "events": attach_countdown(ak_events, now),
        })
        logger.info("明日方舟事件抓取成功: 活动 %d 个 / 版本 %d 个 → %d 个事件",
                    len(ak_acts), len(ak_vers), len(ak_events))
    except Exception as e:  # noqa: BLE001
        logger.warning("明日方舟事件抓取失败（降级空态）: %s", e)
        games_out.append({"game_id": "arknights", "name": "明日方舟", "color": "rose",
                          "source_url": GAMES[1]["source_url"], "events": []})

    _save_cache({"games": games_out})
    return games_out
