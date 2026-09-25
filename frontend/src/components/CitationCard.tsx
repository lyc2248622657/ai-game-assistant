import type { Citation } from '../types'

interface Props {
  citations: Citation[]
}

/** 引用卡片：回答的知识来源，可展开查看原文 */
export function CitationCard({ citations }: Props) {
  if (citations.length === 0) return null
  return (
    <div className="rounded-lg border bg-white p-4">
      <h3 className="mb-2 text-sm font-semibold">引用来源</h3>
      <ul className="space-y-2">
        {citations.map((c) => (
          <li key={c.doc_id} className="rounded border bg-gray-50 p-2 text-xs">
            <div className="font-medium text-blue-700">{c.title}</div>
            <div className="mt-1 line-clamp-3 text-gray-500">{c.snippet}</div>
            {/* TODO(阶段三)：点击展开全文 */}
          </li>
        ))}
      </ul>
    </div>
  )
}
