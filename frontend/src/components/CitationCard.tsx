import type { Citation } from '../types'

interface Props {
  citations: Citation[]
}

/** 引用卡片：回答的知识来源，可展开查看原文 */
export function CitationCard({ citations }: Props) {
  if (citations.length === 0) return null
  return (
    <div className="app-card app-card-hover p-4">
      <h3 className="gradient-text mb-2 text-sm font-bold">引用来源</h3>
      <ul className="space-y-2">
        {citations.map((c) => (
          <li key={c.doc_id} className="rounded-xl border border-gray-100 bg-gradient-to-r from-gray-50 to-indigo-50/40 p-2 text-xs">
            <div className="font-medium text-indigo-700">{c.title}</div>
            <div className="mt-1 line-clamp-3 text-gray-500">{c.snippet}</div>
            {/* TODO(阶段三)：点击展开全文 */}
          </li>
        ))}
      </ul>
    </div>
  )
}
