import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

// mock 全部后端 API 与 SSE，聚焦"页面能否挂载渲染"这一 smoke 目标
vi.mock('./api/client', () => ({
  api: {
    listSessions: () => Promise.resolve([]),
    getMessages: () => Promise.resolve({ messages: [] }),
    getKeyStatus: () => Promise.resolve({ configured: false }),
    createSession: () => Promise.resolve({ session_id: 's1', title: '新对话' }),
    deleteSession: () => Promise.resolve({ ok: true }),
  },
  streamChat: vi.fn(),
  StreamConnectionError: class extends Error {},
  StreamInterruptedError: class extends Error {},
}))

vi.mock('./components/EventCountdown', () => ({ EventCountdown: () => <div>事件倒计时</div> }))
vi.mock('./components/AgentTimeline', () => ({ AgentTimeline: () => <div>决策链路</div> }))
vi.mock('./components/CitationCard', () => ({ CitationCard: () => <div>引用</div> }))
vi.mock('./components/AdminPanel', () => ({ AdminPanel: () => <div>控制台</div> }))
vi.mock('./components/SettingsModal', () => ({
  SettingsModal: () => <div>设置</div>,
}))
vi.mock('./components/SessionBar', () => ({
  SessionBar: () => <div>会话栏</div>,
}))
vi.mock('./components/ChatWindow', () => ({
  ChatWindow: () => <div>聊天窗口</div>,
}))

describe('App smoke', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('挂载渲染出标题与对话 tab（默认视图）', async () => {
    render(<App />)
    expect(await screen.findByText('多游戏智能助手')).toBeInTheDocument()
    expect(screen.getByText('对话')).toBeInTheDocument()
    expect(screen.getByText('管理控制台')).toBeInTheDocument()
  })

  it('聊天区渲染聊天窗口与侧栏', async () => {
    render(<App />)
    expect(await screen.findByText('聊天窗口')).toBeInTheDocument()
    expect(screen.getByText('决策链路')).toBeInTheDocument()
  })
})
