import { useState } from 'react'
import type { SessionInfo } from '../types'

interface Props {
  sessions: SessionInfo[]
  current: SessionInfo | null
  onSelect: (s: SessionInfo) => void
  onCreate: () => void
  onDelete: (s: SessionInfo) => void
}

/** 会话栏：可折叠 + 新建/删除对话（统一对话框，不再按游戏分组） */
export function SessionBar({ sessions, current, onSelect, onCreate, onDelete }: Props) {
  const [collapsed, setCollapsed] = useState(false)

  if (collapsed) {
    return (
      <aside className="flex w-10 flex-col items-center border-r bg-gray-50 py-3">
        <button
          onClick={() => setCollapsed(false)}
          title="展开会话列表"
          className="rounded-lg p-2 text-gray-500 hover:bg-gray-200"
        >
          ☰
        </button>
      </aside>
    )
  }

  return (
    <aside className="flex w-56 flex-col border-r bg-gray-50">
      <div className="flex items-center justify-between border-b p-2">
        <span className="px-1 text-sm font-semibold">会话</span>
        <div className="flex gap-1">
          <button
            onClick={onCreate}
            title="新建对话"
            className="rounded-md bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700"
          >
            ＋ 新对话
          </button>
          <button
            onClick={() => setCollapsed(true)}
            title="折叠会话列表"
            className="rounded-md p-1 text-gray-500 hover:bg-gray-200"
          >
            ◀
          </button>
        </div>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {sessions.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-gray-400">暂无对话，点击"新对话"开始</p>
        )}
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className={`group flex items-center rounded px-2 py-1.5 text-left text-xs ${
              current?.session_id === s.session_id
                ? 'bg-blue-600 text-white'
                : 'text-gray-700 hover:bg-gray-200'
            }`}
          >
            <button onClick={() => onSelect(s)} className="min-w-0 flex-1 truncate">
              {s.title}
            </button>
            <button
              onClick={() => onDelete(s)}
              title="删除对话"
              className={`ml-1 shrink-0 rounded px-1 text-[10px] opacity-0 transition group-hover:opacity-100 ${
                current?.session_id === s.session_id ? 'text-white hover:bg-white/20' : 'text-gray-400 hover:bg-gray-300 hover:text-red-500'
              }`}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
