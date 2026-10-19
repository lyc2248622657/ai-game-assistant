import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { renderMarkdown } from './markdown'

function renderText(text: string): HTMLElement {
  const { container } = render(<div>{renderMarkdown(text)}</div>)
  return container
}

describe('renderMarkdown', () => {
  it('多个 URL 各自指向自己的地址（回归：曾全部指向第一个 URL）', () => {
    const c = renderText('参考 https://a.example/one 和 https://b.example/two 两处')
    const links = Array.from(c.querySelectorAll('a'))
    expect(links).toHaveLength(2)
    expect(links[0].getAttribute('href')).toBe('https://a.example/one')
    expect(links[1].getAttribute('href')).toBe('https://b.example/two')
    expect(links[0].textContent).toContain('a.example')
    expect(links[1].textContent).toContain('b.example')
  })

  it('链接带 noopener noreferrer 且在新标签打开', () => {
    const c = renderText('见 https://a.example/one')
    const a = c.querySelector('a')!
    expect(a.getAttribute('target')).toBe('_blank')
    expect(a.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('粗体与行内代码正常渲染', () => {
    const c = renderText('**重点** 与 `code`')
    expect(c.querySelector('strong')?.textContent).toBe('重点')
    expect(c.querySelector('code')?.textContent).toBe('code')
  })

  it('纯文本不产生链接', () => {
    const c = renderText('这是一段没有链接的话')
    expect(c.querySelectorAll('a')).toHaveLength(0)
    expect(c.textContent).toContain('没有链接')
  })
})
