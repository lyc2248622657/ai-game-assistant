import { useEffect, useState } from 'react'
import { api } from '../api/client'

/** 事件类型 → 图标与文案 */
const TYPE_META: Record<string, { icon: string; label: string }> = {
  version_update: { icon: '🛠️', label: '版本更新' },
  maintenance: { icon: '🔧', label: '维护更新' },
  activity: { icon: '📅', label: '活动开启' },
  gacha: { icon: '⭐', label: '角色卡池' },
  gacha_weapon: { icon: '🗡️', label: '武器卡池' },
  livestream: { icon: '📺', label: '前瞻直播' },
}

/** 游戏 → 主题色（tailwind 类） */
const GAME_THEME: Record<string, { bar: string; chip: string; text: string; ring: string }> = {
  genshin: { bar: 'bg-teal-500', chip: 'bg-teal-50 text-teal-700', text: 'text-teal-700', ring: 'ring-teal-200' },
  arknights: { bar: 'bg-rose-500', chip: 'bg-rose-50 text-rose-700', text: 'text-rose-700', ring: 'ring-rose-200' },
}
const DEFAULT_THEME = { bar: 'bg-slate-500', chip: 'bg-slate-50 text-slate-700', text: 'text-slate-700', ring: 'ring-slate-200' }

interface GameEvents {
  game_id: string
  name: string
  color?: string
  source_url?: string
  events: Array<{
    type: string
    title: string
    start: string
    end?: string
    status: string
    countdown_sec: number | null
    estimated?: boolean
    note?: string
  }>
}

/** 秒 → "X天X小时X分X秒" */
function fmtCountdown(sec: number): string {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (d > 0) return `${d}天 ${h}小时 ${m}分`
  if (h > 0) return `${h}小时 ${m}分 ${s}秒`
  return `${m}分 ${s}秒`
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 游戏重大事件倒计时：不同游戏不同配色，每秒刷新，按类型标签页切换 */
export function EventCountdown() {
  const [games, setGames] = useState<GameEvents[]>([])
  const [now, setNow] = useState(Date.now())
  const [collapsed, setCollapsed] = useState(false)
  const [activeTab, setActiveTab] = useState('all')

  useEffect(() => {
    api.listEvents().then((r) => setGames(r.games)).catch(() => setGames([]))
  }, [])

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  if (games.length === 0) {
    return (
      <div className="rounded-lg border bg-white p-3">
        <h3 className="text-sm font-semibold">⏳ 游戏重大事件</h3>
        <p className="mt-1 text-xs text-gray-400">事件数据加载中…</p>
      </div>
    )
  }

  const liveCount = games.reduce((n, g) => n + g.events.length, 0)

  // 标签页：全部 / 角色卡池 / 武器卡池 / 版本活动 / 版本 / 前瞻（附简要相关信息）
  const TABS: Array<{ key: string; label: string; hint: string }> = [
    { key: 'all', label: '全部', hint: '进行中优先 · 未开始仅近一个月' },
    { key: 'gacha', label: '⭐ 角色卡池', hint: '上下半各 21 天 · 角色以官方公告为准' },
    { key: 'gacha_weapon', label: '🗡️ 武器卡池', hint: '与角色卡池同周期 · 武器以官方公告为准' },
    { key: 'activity', label: '📅 版本活动', hint: '按版本活动周五开启惯例推算 · 以官方公告为准' },
    { key: 'version_update', label: '🛠️ 版本', hint: '每小版本 6 周 · 周三更新（06:00~11:00 维护）' },
    { key: 'livestream', label: '📺 前瞻', hint: '版本更新前约 2 周 · 周五 20:00 直播' },
  ]
  const activeTabMeta = TABS.find((t) => t.key === activeTab)

  return (
    <div className="rounded-lg border bg-white p-3">
      <button
        className="flex w-full items-center justify-between text-left"
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? '展开' : '折叠'}
      >
        <h3 className="text-sm font-semibold">⏳ 游戏重大事件</h3>
        <span className="text-xs text-gray-400">
          {liveCount} 项{collapsed ? ' ▸' : ' ▾'}
        </span>
      </button>

      {!collapsed && (
        <div className="mt-2 space-y-3">
          {/* 类型标签页 */}
          <div className="flex flex-wrap gap-1">
            {TABS.map((t) => {
              const n = t.key === 'all'
                ? games.reduce((m, g) => m + g.events.length, 0)
                : games.reduce((m, g) => m + g.events.filter((e) => e.type === t.key).length, 0)
              const on = activeTab === t.key
              return (
                <button
                  key={t.key}
                  onClick={() => setActiveTab(t.key)}
                  className={`rounded-full px-2 py-0.5 text-[10px] transition-colors ${on ? 'bg-slate-800 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
                >
                  {t.label} {n}
                </button>
              )
            })}
          </div>
          {/* 当前标签简要信息 */}
          {activeTabMeta?.hint && (
            <p className="rounded bg-slate-50 px-2 py-1 text-[10px] text-gray-500">{activeTabMeta.hint}</p>
          )}

          {games.map((g) => {
            const theme = GAME_THEME[g.game_id] ?? DEFAULT_THEME
            const evs = activeTab === 'all' ? g.events : g.events.filter((e) => e.type === activeTab)
            return (
              <div key={g.game_id}>
                <div className={`mb-1 flex items-center gap-1.5 ${theme.text}`}>
                  <span className={`inline-block h-2 w-2 rounded-full ${theme.bar}`} />
                  <span className="text-xs font-semibold">{g.name}</span>
                  <span className="text-[10px] text-gray-400">{evs.length} 项</span>
                </div>
                {evs.length === 0 ? (
                  <p className="rounded bg-gray-50 px-2 py-1.5 text-[11px] text-gray-400">
                    {activeTab === 'all' ? '暂无已公布事件（以官方公告为准）' : '该分类暂无事件'}
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {evs.map((e, i) => {
                      const meta = TYPE_META[e.type] ?? { icon: '📌', label: e.type }
                      // 实时倒计时：upcoming 距开始 / active 距结束（每秒刷新）
                      const hasEnd = e.status === 'active' && !!e.end
                      const target = hasEnd ? new Date(e.end!).getTime() : new Date(e.start).getTime()
                      const cd = hasEnd ? Math.max(0, Math.floor((target - now) / 1000)) : null
                      const isActive = e.status === 'active'
                      return (
                        <div key={i} className={`rounded border p-2 ${isActive ? 'border-amber-200 bg-amber-50' : 'border-gray-100 bg-gray-50'}`}>
                          <div className="flex items-start justify-between gap-1">
                            <span className="flex min-w-0 flex-1 items-start gap-1 text-[12px] font-medium leading-snug text-gray-800">
                              <span className="shrink-0">{meta.icon}</span>
                              <span className="min-w-0 break-words">{e.title}</span>
                              {e.estimated && (
                                <span className={`shrink-0 rounded px-1 text-[9px] ${theme.chip}`}>预计</span>
                              )}
                            </span>
                            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${isActive ? 'bg-amber-100 text-amber-700' : 'bg-white text-gray-500'}`}>
                              {isActive ? (hasEnd ? `进行中 · 剩${fmtCountdown(cd!)}` : '进行中 · 待官方公告') : cd ? `${fmtCountdown(cd)}后` : '即将开启'}
                            </span>
                          </div>
                          <div className="mt-1 space-y-0.5 text-[10px] leading-snug text-gray-400">
                            <div>{fmtDate(e.start)}{e.end ? ` ~ ${fmtDate(e.end)}` : ''}</div>
                            {e.note && <div className="break-words">{e.note}</div>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
          <p className="text-[10px] text-gray-400">
            数据来源：bwiki 版本历史 / PRTS · 预计事件按官方周期规律推算
          </p>
        </div>
      )}
    </div>
  )
}
