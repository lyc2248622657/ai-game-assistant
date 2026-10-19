import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

// 用 hoisted 共享可变状态：可切换"是否需要令牌"，验证鉴权弹窗分支
const mocks = vi.hoisted(() => ({ authorized: true }))

// mock 全部后端 API 与 SSE，聚焦"页面能否挂载渲染 + 鉴权分支"这两个 smoke 目标
vi.mock('./api/client', () => ({
  api: {
    listSessions: () => Promise.resolve([]),
    getMessages: () => Promise.resolve({ messages: [] }),
    getKeyStatus: () => Promise.resolve({ configured: false }),
    createSession: () => Promise.resolve({ session_id: 's1', title: '新对话' }),
    deleteSession: () => Promise.resolve({ ok: true }),
    getAuthStatus: () =>
      Promise.resolve({
        auth_required: !mocks.authorized,
        authorized: mocks.authorized,
        loopback: false,
        token_configured: true,
        token: null,
      }),
    verifyToken: () => Promise.resolve({ ok: true }),
  },
  setToken: () => {},
  getToken: () => '',
  withToken: (u: string) => u,
  streamChat: vi.fn(),
  StreamConnectionError: class extends Error {},
  StreamInterruptedError: class extends Error {},
  AuthRequiredError: class extends Error {},
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
    mocks.authorized = true
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

  it('未授权时显示访问令牌输入页而不是主界面', async () => {
    mocks.authorized = false
    render(<App />)
    expect(await screen.findByText('需要访问令牌')).toBeInTheDocument()
    expect(screen.getByLabelText('访问令牌')).toBeInTheDocument()
    expect(screen.queryByText('聊天窗口')).not.toBeInTheDocument()
  })
})
