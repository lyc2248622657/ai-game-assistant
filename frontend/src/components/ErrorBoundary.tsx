import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  message: string
}

/** 渲染级错误边界：SSE 断流、异步状态异常等不再导致整页白屏 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(err: unknown): State {
    return { hasError: true, message: err instanceof Error ? err.message : String(err) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 保留错误现场：可在此上报；当前项目无遥测，仅打印
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  reset = () => {
    this.setState({ hasError: false, message: '' })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
          <div className="rounded-2xl border border-red-200 bg-red-50 px-6 py-4 text-center shadow-sm">
            <p className="text-sm font-medium text-red-700">
              {this.props.fallbackTitle ?? '页面渲染出现异常'}
            </p>
            <p className="mt-1 max-w-md break-all text-xs text-red-500">{this.state.message}</p>
            <button
              onClick={this.reset}
              className="btn-brand mt-3 rounded-full px-4 py-1.5 text-xs font-medium"
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
