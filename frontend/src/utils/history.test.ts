import { describe, expect, it } from 'vitest'
import { mapHistory, normalizeCitations } from './history'

describe('normalizeCitations', () => {
  it('把 SSE 原始 dict 的 content 映射成 snippet', () => {
    const out = normalizeCitations([{ doc_id: 'd1', title: '胡桃', content: '火系角色', source: 'static' }])
    expect(out).toEqual([{ doc_id: 'd1', title: '胡桃', snippet: '火系角色', source: 'static' }])
  })

  it('已经是 snippet 的原样保留', () => {
    const out = normalizeCitations([{ doc_id: 'd1', title: '胡桃', snippet: '已归一', source: 'static' }])
    expect(out?.[0].snippet).toBe('已归一')
  })

  it('空数组返回 undefined（CitationCard 据此不渲染）', () => {
    expect(normalizeCitations([])).toBeUndefined()
    expect(normalizeCitations(undefined)).toBeUndefined()
  })
})

describe('mapHistory', () => {
  it('保留引用与配图，并映射角色', () => {
    const out = mapHistory([
      { role: 'user', content: '胡桃怎么配队', images: ['/uploads/a.png'] },
      {
        role: 'assistant',
        content: '推荐蒸发队',
        citations: [{ doc_id: 'd1', title: '胡桃蒸发队', content: '双火蒸发' }],
      },
    ])
    expect(out).toHaveLength(2)
    expect(out[0].role).toBe('user')
    expect(out[0].images).toEqual(['/uploads/a.png'])
    expect(out[0].citations).toBeUndefined()
    expect(out[1].role).toBe('assistant')
    expect(out[1].citations?.[0].snippet).toBe('双火蒸发')
  })
})
