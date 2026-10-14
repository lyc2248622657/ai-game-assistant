import { describe, expect, it, vi } from 'vitest'
import {
  parseSSEFrame,
  streamChat,
  StreamConnectionError,
  StreamInterruptedError,
} from '../api/client'

describe('parseSSEFrame', () => {
  it('解析 event + data 帧', () => {
    const { event, data } = parseSSEFrame('event: answer\ndata: {"delta":"你好"}')
    expect(event).toBe('answer')
    expect(data).toBe('{"delta":"你好"}')
  })

  it('无 event 行时默认为 message', () => {
    const { event, data } = parseSSEFrame('data: {"ok":true}')
    expect(event).toBe('message')
    expect(data).toBe('{"ok":true}')
  })

  it('多行 data 拼接（JSON 跨行）', () => {
    const { data } = parseSSEFrame('data: {"a":\ndata: 1}')
    expect(data).toBe('{"a":1}')
  })
})

/** 构造 SSE 响应体流 */
function sseStream(blocks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const b of blocks) controller.enqueue(new TextEncoder().encode(b))
      controller.close()
    },
  })
}

function okResponse(blocks: string[]): Response {
  return new Response(sseStream(blocks), { status: 200 })
}

describe('streamChat 连接重试', () => {
  it('连接层失败自动重试后成功，事件正常到达', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('network down')) // 第 1 次连接失败
      .mockResolvedValueOnce(okResponse(['event: answer\ndata: {"delta":"hi"}\n\n'])) // 第 2 次成功

    const events: string[] = []
    await streamChat('genshin', '你好', null, null, (ev) => events.push(ev.type))

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(events).toEqual(['answer'])
  })

  it('收到部分事件后断流 → 抛 StreamInterruptedError 且不重试', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(okResponse(['event: agent_start\ndata: {"n":1}\n\n'])) // 正常帧后流正常结束——模拟半途断开用 throw

    // 覆盖：已收到事件后 reader.read 抛错（pull 阶段触发 error）
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(encoder.encode('event: agent_start\ndata: {"n":1}\n\n'))
      },
      pull(c) {
        c.error(new TypeError('socket hang up'))
      },
    })
    fetchMock.mockReset()
    fetchMock.mockResolvedValueOnce(new Response(body, { status: 200 }))

    const events: string[] = []
    await expect(
      streamChat('genshin', '你好', null, null, (ev) => events.push(ev.type)),
    ).rejects.toBeInstanceOf(StreamInterruptedError)
    expect(fetchMock).toHaveBeenCalledTimes(1) // 不自动重发
    expect(events).toEqual(['agent_start'])
  })

  it('5xx 视为连接层错误并重试；重试耗尽后抛出', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'boom' }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'boom' }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'boom' }), { status: 503 }))

    await expect(streamChat(null, 'x', null, null, () => {})).rejects.toBeInstanceOf(
      StreamConnectionError,
    )
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('4xx 明确错误直接抛出，不重试', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'bad request' }), { status: 400 }))

    await expect(streamChat(null, 'x', null, null, () => {})).rejects.toThrow('bad request')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
