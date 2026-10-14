import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { GameInfo, VectorCollection, VectorStats } from '../types'

interface SearchHit {
  doc_id: string
  title: string
  content: string
  source?: string
  score?: number
}

/** 管理控制台：知识库运维（增量更新/脏数据清理/检索测试）+ 系统状态
 *  承接方向①：把后端已有 /api/vector/* 运维能力接到 UI，形成「可运维」闭环
 */
export function AdminPanel() {
  const [games, setGames] = useState<GameInfo[]>([])
  const [keyStatus, setKeyStatus] = useState<{ configured: boolean; source?: string | null; masked?: string }>({
    configured: false,
  })
  const [collections, setCollections] = useState<VectorCollection[]>([])
  const [selCollection, setSelCollection] = useState('documents')
  const [stats, setStats] = useState<VectorStats | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // 检索测试
  const [searchGame, setSearchGame] = useState('genshin')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchHits, setSearchHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)

  const refreshStats = (name: string) => {
    api
      .getVectorStats(name)
      .then(setStats)
      .catch(() => setStats(null))
  }

  // 初始加载：游戏 / Key 状态 / 集合列表
  useEffect(() => {
    api
      .listGames()
      .then(({ games }) => setGames(games))
      .catch(() => {})
    api
      .getKeyStatus()
      .then((s) => setKeyStatus({ configured: s.configured, source: s.source, masked: s.masked_key }))
      .catch(() => {})
    api
      .listCollections()
      .then(({ collections }) => {
        setCollections(collections)
        const target = collections.some((c) => c.name === selCollection)
          ? selCollection
          : collections[0]?.name ?? 'documents'
        setSelCollection(target)
        refreshStats(target)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const selectCollection = (name: string) => {
    setSelCollection(name)
    refreshStats(name)
  }

  const run = async (fn: () => Promise<unknown>, okText: string) => {
    setBusy(true)
    setMsg(null)
    try {
      const r = (await fn()) as { message?: string; purged_chunks?: number; deleted_chunks?: number }
      const extra = r?.purged_chunks != null ? `（清理 ${r.purged_chunks} 块）` : r?.deleted_chunks != null ? `（删除 ${r.deleted_chunks} 块）` : ''
      setMsg({ ok: true, text: `${okText} ${extra}`.trim() })
      refreshStats(selCollection)
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const doSearch = async () => {
    const q = searchQuery.trim()
    if (!q) return
    setSearching(true)
    setSearchHits([])
    try {
      const r = await api.searchVector(searchGame, q, 4)
      setSearchHits(r.docs ?? [])
    } catch (e) {
      setMsg({ ok: false, text: `检索测试失败: ${(e as Error).message}` })
    } finally {
      setSearching(false)
    }
  }

  const scoreBadge = (s?: number) => {
    if (typeof s !== 'number') return null
    const pct = Math.round(s * 100)
    const cls =
      s >= 0.8
        ? 'bg-gradient-to-r from-emerald-50 to-teal-50 text-emerald-700 border border-emerald-100'
        : s >= 0.6
          ? 'bg-gradient-to-r from-amber-50 to-orange-50 text-amber-700 border border-amber-100'
          : 'bg-gray-50 text-gray-500 border border-gray-100'
    return <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>{pct}%</span>
  }

  /** by_doc 迷你占比条：以最多块的文档为基准（max 已知时） */
  const docMax = stats ? Math.max(1, ...Object.values(stats.by_doc)) : 1

  return (
    <div className="nice-scroll flex flex-1 gap-4 overflow-hidden p-4">
      {/* 左列：系统状态 + 知识库管理 */}
      <div className="nice-scroll flex w-[46%] flex-col gap-3 overflow-y-auto">
        {/* 系统状态 */}
        <div className="app-card app-card-hover p-3">
          <h3 className="gradient-text text-sm font-bold">🖥️ 系统状态</h3>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <div className="rounded-xl bg-gradient-to-br from-indigo-50 to-violet-50 p-2.5 text-center">
              <div className="gradient-text text-2xl font-bold">{games.length}</div>
              <div className="text-[10px] text-gray-500">已接入游戏</div>
            </div>
            <div className="rounded-xl bg-gradient-to-br from-emerald-50 to-teal-50 p-2.5 text-center">
              <div className="text-2xl font-bold text-emerald-600">{collections.length}</div>
              <div className="text-[10px] text-gray-500">知识库集合</div>
            </div>
            <div className="rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 p-2.5 text-center">
              <div className="text-2xl font-bold text-amber-600">{stats?.total ?? '—'}</div>
              <div className="text-[10px] text-gray-500">向量块总数</div>
            </div>
          </div>
          <div className="mt-3 space-y-2">
            <div>
              <div className="text-xs text-gray-500">已接入游戏</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {games.map((g) => (
                  <span
                    key={g.game_id}
                    className={`rounded-full px-2.5 py-0.5 text-xs ${
                      g.enabled ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-400'
                    }`}
                  >
                    {g.name} {g.enabled ? '' : '（停用）'}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">模型连接</div>
              <div className="mt-1 text-xs">
                {keyStatus.configured ? (
                  <span className="text-green-600">
                    ✓ 已配置（{keyStatus.source === 'app_settings' ? '应用内设置' : '本地文件/环境变量'}）：
                    <code className="font-mono">{keyStatus.masked}</code>
                  </span>
                ) : (
                  <span className="text-amber-600">未配置 API Key —— 请先在 ⚙ 设置中填写</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* 知识库管理 */}
        <div className="app-card app-card-hover p-3">
          <h3 className="gradient-text text-sm font-bold">📚 知识库管理</h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {collections.map((c) => (
              <button
                key={c.name}
                onClick={() => selectCollection(c.name)}
                className={`rounded-full px-2.5 py-1 text-xs transition ${
                  c.name === selCollection
                    ? 'btn-brand font-medium'
                    : 'border border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'
                }`}
              >
                {c.name} · {c.count}
              </button>
            ))}
          </div>

          {stats && (
            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-lg bg-gradient-to-r from-indigo-50 to-violet-50 px-2 py-1 font-medium text-indigo-700">
                  总块数 {stats.total}
                </span>
                {Object.entries(stats.by_source).map(([src, n]) => (
                  <span key={src} className="rounded-lg bg-gray-50 px-2 py-1 text-gray-600">
                    {src} × {n}
                  </span>
                ))}
                {stats.orphan_chunk_count > 0 ? (
                  <button
                    onClick={() => run(() => api.purgeVector(selCollection), '已清理孤儿块')}
                    disabled={busy}
                    className="rounded-lg bg-red-50 px-2 py-1 text-red-600 transition hover:bg-red-100 disabled:opacity-50"
                  >
                    清理孤儿块 {stats.orphan_chunk_count} 个
                  </button>
                ) : (
                  <span className="rounded-lg bg-gradient-to-r from-emerald-50 to-teal-50 px-2 py-1 text-emerald-700">
                    无孤儿块 ✓
                  </span>
                )}
              </div>

              <div className="space-y-1">
                {Object.entries(stats.by_doc).length === 0 && (
                  <p className="text-xs text-gray-400">该集合暂无文档</p>
                )}
                {Object.entries(stats.by_doc).map(([doc, n]) => (
                  <div
                    key={doc}
                    className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50/60 px-2.5 py-1.5 transition hover:border-indigo-100 hover:bg-indigo-50/30"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-xs text-gray-700" title={doc}>
                          {doc}
                        </span>
                        <span className="shrink-0 text-[10px] text-gray-400">{n} 块</span>
                      </div>
                      <div className="mt-1 h-[5px] overflow-hidden rounded-full bg-gray-200/70">
                        <div className="mini-bar" style={{ width: `${Math.max(6, (n / docMax) * 100)}%` }} />
                      </div>
                    </div>
                    <button
                      onClick={() => run(() => api.rebuildVectorDoc(doc), `已重建 ${doc}`)}
                      disabled={busy}
                      className="shrink-0 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10px] text-indigo-600 transition hover:bg-indigo-100 disabled:opacity-50"
                    >
                      重建
                    </button>
                    <button
                      onClick={() => run(() => api.deleteVectorDoc(selCollection, doc), `已删除 ${doc}`)}
                      disabled={busy}
                      className="shrink-0 rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] text-red-600 transition hover:bg-red-100 disabled:opacity-50"
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {msg && (
            <div
              className={`mt-2 rounded-lg px-2.5 py-1.5 text-xs ${
                msg.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
              }`}
            >
              {msg.text}
            </div>
          )}
        </div>
      </div>

      {/* 右列：检索测试 */}
      <div className="nice-scroll flex flex-1 flex-col gap-3 overflow-y-auto">
        <div className="app-card app-card-hover p-3">
          <h3 className="gradient-text text-sm font-bold">🔍 检索测试（RAG 召回核验）</h3>
          <div className="mt-2 flex gap-2">
            <select
              value={searchGame}
              onChange={(e) => setSearchGame(e.target.value)}
              className="shrink-0 rounded-xl border border-gray-200 px-2 py-1.5 text-xs outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-200/60"
            >
              {games.map((g) => (
                <option key={g.game_id} value={g.game_id}>
                  {g.name}
                </option>
              ))}
            </select>
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
              placeholder="输入测试问题，如：胡桃技能数值 / 银灰培养材料"
              className="min-w-0 flex-1 rounded-xl border border-gray-200 px-3 py-1.5 text-sm outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-200/60"
            />
            <button
              onClick={doSearch}
              disabled={searching || !searchQuery.trim()}
              className="btn-brand shrink-0 rounded-xl px-3 py-1.5 text-sm font-medium"
            >
              {searching ? '检索中…' : '检索'}
            </button>
          </div>

          <div className="mt-3 space-y-2">
            {searchHits.length === 0 && !searching && (
              <p className="text-xs text-gray-400">检索结果会显示来源文档与相似度，用于核验召回质量</p>
            )}
            {searchHits.map((h, i) => (
              <div
                key={h.doc_id || i}
                className="rounded-xl border border-amber-100 bg-gradient-to-r from-amber-50/60 to-orange-50/40 px-3 py-2 transition hover:border-amber-200"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-gray-700" title={h.title}>
                    {i + 1}. {h.title}
                  </span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {h.source && <span className="text-[10px] text-gray-400">{h.source}</span>}
                    {scoreBadge(h.score)}
                  </div>
                </div>
                {h.content && (
                  <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-gray-500">{h.content}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
