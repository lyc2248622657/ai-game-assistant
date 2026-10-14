import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary from './ErrorBoundary'

function Bomb(): JSX.Element {
  throw new Error('渲染爆炸')
}

function Safe(): JSX.Element {
  return <div>正常内容</div>
}

describe('ErrorBoundary', () => {
  it('子组件正常时不渲染兜底', () => {
    render(
      <ErrorBoundary>
        <Safe />
      </ErrorBoundary>,
    )
    expect(screen.getByText('正常内容')).toBeInTheDocument()
  })

  it('子组件抛错时显示兜底与重试按钮，不白屏', () => {
    // 抑制 React 在测试中的错误日志噪音
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/页面渲染出现异常/)).toBeInTheDocument()
    expect(screen.getByText('渲染爆炸')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    spy.mockRestore()
  })
})
