"""事件倒计时引擎纯逻辑测试：版本推算 / 卡池 / 活动 / 状态判定 / 优先级排序 / 明日方舟

不联网：使用固定版本表样本，仅测本地计算逻辑。
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.events.engine import (  # noqa: E402
    _parse_ak_time,
    attach_countdown,
    derive_ak_events,
    derive_upcoming,
    merge_gacha,
)


NOW = datetime(2026, 9, 24, 12, 0, 0)


def _table():
    """模拟 bwiki 版本历史：7.0 于 2026-08-12 更新（周三）"""
    return [{"version": "7.0", "start": datetime(2026, 8, 12), "activity": "「无神怜爱的雪国」"}]


def test_derive_updates_on_wednesday():
    """版本更新日均为周三，且间隔 6 周"""
    evs = derive_upcoming(_table(), horizon=2, now=NOW)
    updates = [e for e in evs if e["type"] == "version_update" and "进行中" not in e["title"]]
    assert len(updates) >= 1
    for u in updates:
        dt = datetime.fromisoformat(u["start"])
        assert dt.weekday() == 2, "版本更新应为周三"
        assert u["estimated"] is True


def test_derive_has_active_version():
    """推算窗口顺延后应存在"进行中"版本事件（active）"""
    evs = derive_upcoming(_table(), horizon=2, now=NOW)
    out = attach_countdown(evs, NOW)
    active = [e for e in out if e["status"] == "active"]
    assert any("进行中" in e["title"] for e in active), "应存在进行中的版本事件"


def test_derive_gacha_and_activity():
    """每个版本应有上下半卡池 + 版本活动，且时间落在版本窗口内"""
    evs = derive_upcoming(_table(), horizon=1, now=NOW)
    gachas = [e for e in evs if e["type"] == "gacha"]
    acts = [e for e in evs if e["type"] == "activity"]
    assert len(gachas) >= 2
    assert len(acts) >= 1
    for g in gachas[:2]:
        s = datetime.fromisoformat(g["start"])
        e = datetime.fromisoformat(g["end"])
        assert (e - s).days == 21, "卡池周期应为 21 天"
        assert g["estimated"] is True


def test_derive_livestream_before_update():
    """前瞻直播应早于对应版本更新约 14 天（取未来版本事件）"""
    evs = derive_upcoming(_table(), horizon=2, now=NOW)
    upd = next(e for e in evs if e["type"] == "version_update" and "进行中" not in e["title"])
    live = next(e for e in evs if e["type"] == "livestream")
    delta = datetime.fromisoformat(upd["start"]) - datetime.fromisoformat(live["start"])
    assert 10 <= delta.days <= 16, "前瞻直播应早于版本更新约 2 周"


def test_status_upcoming_active_ended():
    """状态判定：未开始=upcoming / 进行中=active / 已结束过滤"""
    evs = [
        {"title": "未来", "type": "activity", "start": "2026-10-01T06:00:00", "end": "2026-10-15T03:59:59"},
        {"title": "进行中", "type": "activity", "start": "2026-09-20T06:00:00", "end": "2026-09-30T03:59:59"},
        {"title": "已结束", "type": "activity", "start": "2026-09-01T06:00:00", "end": "2026-09-10T03:59:59"},
    ]
    out = attach_countdown(evs, NOW)
    titles = [e["title"] for e in out]
    assert "已结束" not in titles
    future = next(e for e in out if e["title"] == "未来")
    active = next(e for e in out if e["title"] == "进行中")
    assert future["status"] == "upcoming"
    assert active["status"] == "active"
    assert future["countdown_sec"] > 0
    assert active["countdown_sec"] > 0


def test_sort_priority_active_first():
    """优先级排序：进行中在前，同类内按倒计时升序（紧迫优先）"""
    evs = [
        {"title": "远未来", "type": "activity", "start": "2026-10-20T06:00:00", "end": "2026-11-03T03:59:59"},
        {"title": "进行中A", "type": "activity", "start": "2026-09-10T06:00:00", "end": "2026-09-28T03:59:59"},
        {"title": "进行中B", "type": "activity", "start": "2026-09-10T06:00:00", "end": "2026-10-10T03:59:59"},
        {"title": "近未来", "type": "activity", "start": "2026-10-01T06:00:00", "end": "2026-10-15T03:59:59"},
    ]
    out = attach_countdown(evs, NOW)
    assert out[0]["title"] == "进行中A"   # active 且距结束最近
    assert out[1]["title"] == "进行中B"
    assert out[2]["title"] == "近未来"    # upcoming 按距开始升序
    assert out[3]["title"] == "远未来"


def test_upcoming_window_30_days():
    """未开始事件只显示近一个月（>30 天过滤），进行中不受限"""
    evs = [
        {"title": "进行中", "type": "activity", "start": "2026-09-10T06:00:00", "end": "2026-10-05T03:59:59"},
        {"title": "10天后", "type": "activity", "start": "2026-10-04T06:00:00", "end": "2026-10-20T03:59:59"},
        {"title": "40天后", "type": "activity", "start": "2026-11-03T06:00:00", "end": "2026-11-18T03:59:59"},
        {"title": "60天后", "type": "activity", "start": "2026-11-23T06:00:00", "end": "2026-12-08T03:59:59"},
    ]
    out = attach_countdown(evs, NOW)
    titles = [e["title"] for e in out]
    assert "进行中" in titles          # active 保留
    assert "10天后" in titles          # 窗口内 upcoming 保留
    assert "40天后" not in titles      # 超窗 upcoming 过滤
    assert "60天后" not in titles


def test_merge_gacha_real_pool():
    """祈愿页真实卡池覆盖推算事件：title 换卡池名、时间官方、estimated=False"""
    events = [
        {"type": "gacha", "title": "版本 7.1 上半卡池（预计）",
         "start": "2026-09-23T06:00:00", "end": "2026-10-14T06:00:00",
         "estimated": True, "note": "推算"},
        {"type": "gacha", "title": "版本 7.1 下半卡池（预计）",
         "start": "2026-10-14T06:00:00", "end": "2026-11-04T06:00:00",
         "estimated": True, "note": "推算"},
    ]
    pools = [
        {"pool_name": "涌浪叙歌", "kind": "角色", "version": "7.1上半",
         "start": "2026/09/23 06:00", "end": "2026/10/13 17:59",
         "chars_5": ["「幽歌萦渊·沃雅妮莎(水)」"], "chars_4": ["「猫尾特调·迪奥娜(冰)」"],
         "weapons_5": [], "weapons_4": []},
        {"pool_name": "煦风欢舞时", "kind": "角色", "version": "7.1上半",
         "start": "2026/09/23 06:00", "end": "2026/10/13 17:59",
         "chars_5": ["「雪宴之锋·薇斯纳(风)」"], "chars_4": [],
         "weapons_5": [], "weapons_4": []},
        {"pool_name": "神铸赋形", "kind": "武器", "version": "7.1上半",
         "start": "2026/09/23 06:00", "end": "2026/10/13 17:59",
         "chars_5": [], "chars_4": [], "weapons_5": ["「单手剑·蝶变」"], "weapons_4": []},
    ]
    out = merge_gacha(events, pools)
    top = next(e for e in out if "涌浪叙歌" in e["title"])
    assert "煦风欢舞时" in top["title"], "并开双池应合并展示"
    assert "幽歌萦渊·沃雅妮莎" in top["note"]
    assert "雪宴之锋·薇斯纳" in top["note"]
    assert top["estimated"] is False
    assert top["end"].startswith("2026-10-13T17:59"), "官方结束时间应覆盖推算值"
    lower = next(e for e in out if "下半" in e["title"])
    assert lower["estimated"] is True
    assert "涌浪叙歌" not in lower["title"]
    # 武器卡池独立事件（gacha_weapon）
    wp = next(e for e in out if e["type"] == "gacha_weapon")
    assert "神铸赋形" in wp["title"]
    assert "蝶变" in wp["note"]
    assert wp["estimated"] is False
    assert wp["end"].startswith("2026-10-13T17:59")


def test_derive_activity_name_when_official_version():
    """进行中为已公布版本时，版本活动事件带真实活动名"""
    tbl = [{"version": "7.0", "start": datetime(2026, 8, 12),
            "version_name": "「无神怜爱的雪国」", "activity": "「险境征者竞锋大赛」"}]
    evs = derive_upcoming(tbl, horizon=1, now=datetime(2026, 9, 1))
    act = next(e for e in evs if e["type"] == "activity")
    assert "险境征者竞锋大赛" in act["title"], "进行中版本的版本活动应带真实活动名"


# ---------------------------------------------------------------------------
# 明日方舟事件（bwiki 活动关卡 + 更新记录）
# ---------------------------------------------------------------------------
def test_parse_ak_time_formats():
    """明日方舟时间格式：带/不带前导零均可解析"""
    dt = _parse_ak_time("2026年09月28日 04:00")
    assert dt == datetime(2026, 9, 28, 4, 0)
    dt2 = _parse_ak_time("2026年3月14日 16:00")
    assert dt2 == datetime(2026, 3, 14, 16, 0)
    assert _parse_ak_time("2026年无时间") is None


def test_derive_ak_events_real_data():
    """明日方舟事件组合：真实活动起止 + 最新版本（无卡池，不编造）"""
    acts = [
        {"name": "锦枫映月签到活动", "start": datetime(2026, 9, 23, 4), "end": datetime(2026, 9, 30, 3, 59), "kind": "signin"},
        {"name": "稳态测定签到活动", "start": datetime(2026, 9, 28, 4), "end": datetime(2026, 10, 8, 3, 59), "kind": "signin"},
        {"name": "SideStory「月行水上」", "start": datetime(2026, 9, 4, 12), "end": datetime(2026, 9, 25, 3, 59), "kind": "sidesstory"},
    ]
    vers = [{"version": "2.7.61", "date": "2026-07-31", "note": "2026「夏日嘉年华」限时活动开启"}]
    now = datetime(2026, 9, 25, 12, 0)
    evs = derive_ak_events(acts, vers, now)
    types = {e["type"] for e in evs}
    assert "activity" in types
    assert "version_update" in types
    assert "gacha" not in types, "无官方卡池排期源，不得生成卡池事件"
    # 版本事件：真实数据、无结束时间（end=None 表示待官方公告）
    ver = next(e for e in evs if e["type"] == "version_update")
    assert ver["estimated"] is False
    assert ver["end"] is None
    assert "2.7.61" in ver["title"]


def test_attach_countdown_ak():
    """明日方舟事件倒计时：进行中版本（end=None）cds=None；已结束过滤；即将开始正常倒计时"""
    acts = [
        {"name": "锦枫映月签到活动", "start": datetime(2026, 9, 23, 4), "end": datetime(2026, 9, 30, 3, 59), "kind": "signin"},
        {"name": "稳态测定签到活动", "start": datetime(2026, 9, 28, 4), "end": datetime(2026, 10, 8, 3, 59), "kind": "signin"},
        {"name": "SideStory「月行水上」", "start": datetime(2026, 9, 4, 12), "end": datetime(2026, 9, 25, 3, 59), "kind": "sidesstory"},
    ]
    vers = [{"version": "2.7.61", "date": "2026-07-31", "note": "..."}]
    now = datetime(2026, 9, 25, 12, 0)
    out = attach_countdown(derive_ak_events(acts, vers, now), now)
    # 已结束的 SideStory 过滤
    assert not any("月行水上" in e["title"] for e in out), "已结束活动应过滤"
    # 进行中版本：active + cds=None（待官方公告）
    ver = next(e for e in out if e["type"] == "version_update")
    assert ver["status"] == "active"
    assert ver["countdown_sec"] is None
    # 进行中签到活动：active + 正常倒计时
    active_act = next(e for e in out if "锦枫映月" in e["title"])
    assert active_act["status"] == "active"
    assert active_act["countdown_sec"] > 0
    # 即将开始：upcoming
    up = next(e for e in out if "稳态测定" in e["title"])
    assert up["status"] == "upcoming"
    assert up["countdown_sec"] > 0
    # 无结束时间的进行中版本排最前
    assert out[0]["type"] == "version_update"
