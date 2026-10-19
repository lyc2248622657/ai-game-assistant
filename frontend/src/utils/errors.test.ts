import { describe, expect, it } from 'vitest'
import { describeError } from './errors'

describe('describeError', () => {
  it('配置缺失（10007）给出打开设置的建议', () => {
    const advice = describeError(10007, '尚未配置 API Key')
    expect(advice.openSettings).toBe(true)
    expect(advice.hint).toContain('设置')
    // 文案与原始 message 相同时不重复拼接
    expect(advice.text).toBe('尚未配置 API Key')
  })

  it('令牌错误（10008）提示去哪拿令牌', () => {
    const advice = describeError(10008, '需要访问令牌：请在设置中填写')
    expect(advice.text).toContain('需要访问令牌')
    expect(advice.hint).toContain('.api_token')
    expect(advice.openSettings).toBeFalsy()
  })

  it('已知码 + 不同 message 时把细节拼进去', () => {
    const advice = describeError(10005, 'query_game_entity 缺少必填参数: name')
    expect(advice.text).toContain('工具执行失败')
    expect(advice.text).toContain('缺少必填参数')
  })

  it('未知码回落到原始 message', () => {
    const advice = describeError(undefined, '连接被重置')
    expect(advice.text).toBe('连接被重置')
  })

  it('完全没信息时给兜底文案', () => {
    expect(describeError().text).toContain('请求失败')
  })
})
