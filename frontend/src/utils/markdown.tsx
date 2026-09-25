/**
 * 轻量 Markdown 渲染器（零依赖、白名单语法、无 XSS）
 *
 * 支持：**粗体** / *斜体* / `行内代码` / https? URL 自动转超链接（新标签打开）
 *      / 编号列表（1. 2. 3.）/ 无序列表（- / *）/ 段落（空行分隔）
 *
 * 安全：不渲染原始 HTML；URL 仅匹配 http(s)，链接加 rel=noopener noreferrer。
 */
import React from 'react'

const URL_RE = /(https?:\/\/[^\s)\]>，。；、"'）]+)/g

/** 行内解析：URL → <a>，`code` → <code>，**bold** → <strong>，*em* → <em> */
function renderInline(text: string, keyBase: string): React.ReactNode[] {
  // 1) 先保护 URL（其中的 * 不应被当作强调标记）
  const protectedParts: string[] = []
  const urlMasked = text.split(URL_RE).map((seg) => {
    if (URL_RE.test(seg) || /^https?:\/\//.test(seg)) {
      protectedParts.push(seg)
      return `\u0000URL${protectedParts.length - 1}\u0000`
    }
    return seg
  })

  const nodes: React.ReactNode[] = []
  let key = 0
  const pushInline = (raw: string) => {
    if (!raw) return
    // 粗体 **x**（先处理，避免与斜体混淆）
    const boldParts = raw.split(/\*\*(.+?)\*\*/g)
    for (let bi = 0; bi < boldParts.length; bi++) {
      const part = boldParts[bi]
      if (part === '') continue
      if (bi % 2 === 1) {
        nodes.push(<strong key={`${keyBase}-b${key++}`}>{renderInlineNoUrl(part, `${keyBase}-bi${key}`)}</strong>)
      } else {
        nodes.push(...renderInlineNoUrl(part, `${keyBase}-t${key++}`))
      }
    }
  }

  const renderInlineNoUrl = (raw: string, k: string): React.ReactNode[] => {
    const out: React.ReactNode[] = []
    // 行内代码
    const codeParts = raw.split(/`([^`]+)`/g)
    for (let ci = 0; ci < codeParts.length; ci++) {
      const part = codeParts[ci]
      if (part === '') continue
      if (ci % 2 === 1) {
        out.push(<code key={`${k}-c${ci}`} className="rounded bg-gray-100 px-1 py-0.5 text-[11px] font-mono text-gray-800">{part}</code>)
      } else {
        // 斜体 *x*（非粗体残留）
        const emParts = part.split(/(?<!\*)\*([^*\n]+)\*(?!\*)/g)
        for (let ei = 0; ei < emParts.length; ei++) {
          const ep = emParts[ei]
          if (ep === '') continue
          if (ei % 2 === 1) {
            out.push(<em key={`${k}-e${ei}`} className="italic">{ep}</em>)
          } else {
            out.push(ep)
          }
        }
      }
    }
    return out
  }

  for (let i = 0; i < urlMasked.length; i++) {
    const seg = urlMasked[i]
    if (seg.startsWith('\u0000URL')) {
      const idx = Number(seg.slice(5, -1))
      const url = protectedParts[idx]
      const display = url.length > 48 ? url.slice(0, 46) + '…' : url
      nodes.push(
        <a key={`${keyBase}-a${key++}`} href={url} target="_blank" rel="noopener noreferrer"
           className="text-blue-600 underline decoration-blue-300 underline-offset-2 hover:text-blue-500 break-all">
          {display}
        </a>,
      )
    } else {
      pushInline(seg)
    }
  }
  return nodes
}

/** 整段 Markdown → React 节点（段落 / 列表 / 标题 / 分割线） */
export function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: React.ReactNode[] = []
  let para: string[] = []
  let listItems: Array<{ ordered: boolean; num?: number; content: string }> = []
  let listOrdered = false
  let key = 0

  const flushPara = () => {
    if (para.length > 0) {
      blocks.push(
        <p key={`p${key++}`} className="mb-1.5 leading-relaxed">
          {para.map((l, i) => (
            <React.Fragment key={i}>
              {i > 0 && <br />}
              {renderInline(l, `p${key}-${i}`)}
            </React.Fragment>
          ))}
        </p>,
      )
      para = []
    }
  }
  const flushList = () => {
    if (listItems.length === 0) return
    const items = listItems
    const ordered = listOrdered
    blocks.push(
      <div key={`l${key++}`} className={`mb-2 ${ordered ? 'list-decimal' : 'list-disc'} pl-4 space-y-0.5`}>
        {items.map((it, i) => (
          <div key={i} className="flex gap-1.5">
            <span className="shrink-0 text-gray-400 select-none">{ordered ? `${it.num ?? i + 1}.` : '•'}</span>
            <span className="leading-relaxed">{renderInline(it.content, `li${key}-${i}`)}</span>
          </div>
        ))}
      </div>,
    )
    listItems = []
    listOrdered = false
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed === '') {
      flushPara()
      flushList()
      continue
    }
    if (/^#{1,4}\s/.test(trimmed)) {
      flushPara(); flushList()
      const level = trimmed.match(/^(#{1,4})\s/)?.[1].length ?? 1
      const content = trimmed.replace(/^#{1,4}\s+/, '')
      blocks.push(
        <div key={`h${key++}`} className={`mb-1 font-semibold text-gray-800 ${level <= 2 ? 'text-[14px]' : 'text-[13px]'}`}>
          {renderInline(content, `h${key}`)}
        </div>,
      )
      continue
    }
    if (/^[-*]\s+/.test(trimmed)) {
      flushPara()
      listItems.push({ ordered: false, content: trimmed.replace(/^[-*]\s+/, '') })
      continue
    }
    const ord = trimmed.match(/^(\d{1,2})[.、]\s+(.*)$/)
    if (ord) {
      flushPara()
      listItems.push({ ordered: true, num: Number(ord[1]), content: ord[2] })
      listOrdered = true
      continue
    }
    if (/^---+$/.test(trimmed)) {
      flushPara(); flushList()
      blocks.push(<hr key={`hr${key++}`} className="my-1.5 border-gray-200" />)
      continue
    }
    flushList()
    para.push(line)
  }
  flushPara()
  flushList()
  return blocks
}
