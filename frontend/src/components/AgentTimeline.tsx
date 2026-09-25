import { useState } from 'react'
import type { AgentEvent } from '../types'

interface Props {
  events: AgentEvent[]
}

/** 单条事件渲染 */
function EventItem({ ev }: { ev: AgentEvent }) {
  switch (ev.type) {
    case 'agent_start':
      return (
        <div className="flex items-start gap-2 text-xs">
          <span className="mt-0.5 h-2 w-2 shrink-0 animate-pulse rounded-full bg-blue-500" />
          <span className="font-medium text-gray-800">
            {ev.node_name === 'reflect' ? '🔍 ' : ''}
            {ev.message || ev.node_name}
          </span>
        </div>
      )
    case 'agent_end':
      return (
        <div className="flex items-start gap-2 text-xs text-gray-500">
          <span className="mt-1 shrink-0 pl-1 text-[10px]">
            {ev.node_name === 'reflect' && String(ev.summary || '').includes('质检通过') ? '✅' : '✓'}
          </span>
          <span>{ev.summary}</span>
        </div>
      )
    case 'tool_call':
      return (
        <div className="rounded border border-blue-100 bg-blue-50 px-2 py-1 text-xs">
          <span className="font-medium text-blue-700">🔧 {ev.message}</span>
          {ev.arguments && (
            <pre className="mt-1 max-h-20 overflow-auto whitespace-pre-wrap break-all text-[10px] text-gray-500">
              {JSON.stringify(ev.arguments, null, 1)}
            </pre>
          )}
        </div>
      )
    case 'tool_result':
      return (
        <div className="rounded border border-green-100 bg-green-50 px-2 py-1 text-xs">
          <span className="font-medium text-green-700">{ev.message}</span>
          {ev.result && (
            <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-all text-[10px] text-gray-500">
              {ev.result}
            </pre>
          )}
        </div>
      )
    case 'tasks':
      return (
        <div className="rounded border border-violet-100 bg-violet-50 px-2 py-1 text-xs">
          <span className="font-medium text-violet-700">🗂️ {ev.message || `规划 ${ev.tasks?.length ?? 0} 个子任务`}</span>
          <div className="mt-1 space-y-0.5">
            {(ev.tasks ?? []).map((t, i) => (
              <div key={i} className="flex items-center gap-1.5 text-[11px] text-gray-600">
                <span className="shrink-0 rounded bg-white px-1 py-0.5 font-medium text-violet-600">
                  {t.task || `子任务${i + 1}`}
                </span>
                <span className="truncate">{t.description || '—'}</span>
                {t.suggested_tool && (
                  <span className="shrink-0 rounded bg-white/70 px-1 py-0.5 text-[10px] text-gray-400">
                    ↳ {t.suggested_tool}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )
    case 'retrieval':
      return (
        <div className="rounded border border-amber-100 bg-amber-50 px-2 py-1 text-xs">
          <span className="font-medium text-amber-700">📚 检索命中 {ev.docs?.length ?? 0} 条</span>
          <div className="mt-1 flex flex-wrap gap-1">
            {(ev.docs ?? []).map((d, i) => (
              <span key={i} className="rounded bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
                {String(d.title)}
              </span>
            ))}
          </div>
        </div>
      )
    case 'subagent':
      return (
        <div className="rounded border border-indigo-100 bg-indigo-50 px-2 py-1 text-xs">
          <span className="font-medium text-indigo-700">🤝 {ev.message || '主管委派子代理'}</span>
          {ev.brief && (
            <div className="mt-1 rounded bg-white/70 px-1.5 py-0.5 text-[11px] text-gray-600">
              任务：{String(ev.brief)}
            </div>
          )}
        </div>
      )
    case 'replan':
      return (
        <div className="rounded border border-orange-100 bg-orange-50 px-2 py-1 text-xs">
          <span className="font-medium text-orange-700">🔁 {ev.message || '动态调整计划'}</span>
          {(ev.remaining ?? []).length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {(ev.remaining ?? []).map((t, i) => (
                <span key={i} className="rounded bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
                  {String(t.task)} {t.suggested_tool ? `↳ ${t.suggested_tool}` : ''}
                </span>
              ))}
            </div>
          )}
        </div>
      )
    default:
      return null
  }
}

/** 折叠态摘要：最近几条关键事件 */
function CollapsedSummary({ events }: { events: AgentEvent[] }) {
  const key = (ev: AgentEvent) =>
    ev.type === 'tool_call' ? `🔧 ${ev.tool_name}` :
    ev.type === 'subagent' ? `🤝 ${ev.identity || '子代理'}` :
    ev.type === 'replan' ? `🔁 ${ev.remaining?.length ?? 0} 项补充` :
    ev.type === 'tasks' ? `🗂️ ${ev.tasks?.length ?? 0} 个子任务` :
    ev.type === 'retrieval' ? `📚 ${ev.docs?.length ?? 0} 条` :
    ev.type === 'agent_end' ? ev.summary : ''
  const items = events.filter((e) => key(e)).map(key).slice(-3)
  return (
    <div className="flex flex-wrap items-center gap-1 text-[11px] text-gray-500">
      {items.length === 0 && <span>暂无执行记录</span>}
      {items.map((k, i) => (
        <span key={i} className="rounded bg-gray-100 px-1.5 py-0.5">{k}</span>
      ))}
    </div>
  )
}

/** Agent 决策链路时间线：默认折叠成摘要条，点击展开完整过程 */
export function AgentTimeline({ events }: Props) {
  const [open, setOpen] = useState(false)
  const hasEvents = events.length > 0

  return (
    <div className="rounded-lg border bg-white p-3">
      <button
        className="flex w-full items-center justify-between text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <h3 className="text-sm font-semibold">🤖 Agent 决策链路</h3>
        <span className="text-xs text-gray-400">
          {hasEvents ? `${events.length} 条` : ''} {open ? '▾' : '▸'}
        </span>
      </button>

      {open ? (
        <div className="mt-2 space-y-2">
          {hasEvents ? (
            events.map((ev, i) => <EventItem key={i} ev={ev} />)
          ) : (
            <p className="text-xs text-gray-400">发送消息后，这里将实时展示每个 Agent 节点的执行过程</p>
          )}
        </div>
      ) : (
        <div className="mt-2">
          {hasEvents ? <CollapsedSummary events={events} /> : <p className="text-xs text-gray-400">发送消息后实时展示</p>}
        </div>
      )}
    </div>
  )
}
