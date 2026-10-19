/** 错误码 → 用户可操作提示。
 *
 * 后端统一返回 {code, message}，但 message 是"给开发看的"；
 * 产品上更该告诉用户"接下来做什么"。这里集中映射，避免散落在组件里。
 * 错误码定义见 backend/app/core/errors.py。
 */

export interface ErrorAdvice {
  /** 展示给用户的文案（含 message，便于排查） */
  text: string
  /** 可操作建议（没有则为 undefined） */
  hint?: string
  /** 是否应该直接打开设置面板 */
  openSettings?: boolean
}

const ADVICE: Record<number, ErrorAdvice> = {
  10001: { text: '请求参数有误', hint: '检查输入内容（长度 1~4000 字）后重试' },
  10002: { text: '游戏不存在或未启用', hint: '在 config/games.yaml 中确认已登记并启用该游戏' },
  10003: { text: '会话不存在', hint: '新建一个对话，或从左侧选择一个已有会话' },
  10004: { text: '模型调用失败', hint: '检查网络连通性与 Key 额度，稍后重试' },
  10005: { text: '工具执行失败', hint: '换个问法，或把问题范围缩小一些再试' },
  10006: { text: '检索无结果', hint: '知识库里暂未收录相关内容，可换关键词或用「补充资料」提交' },
  10007: {
    text: '尚未配置 API Key',
    hint: '点右上角 ⚙ 设置填写 DeepSeek API Key 后即可使用',
    openSettings: true,
  },
  10008: {
    text: '需要访问令牌',
    hint: '令牌在服务端 backend/app_data/.api_token，或部署时设置的 API_TOKEN',
  },
  10000: { text: '服务器内部错误', hint: '可查看服务端日志定位；稍后重试通常有效' },
}

/** 把后端错误变成"用户可操作"的建议 */
export function describeError(code?: number, message?: string): ErrorAdvice {
  const base = code != null ? ADVICE[code] : undefined
  const detail = (message || '').trim()
  if (base) {
    return {
      ...base,
      text: detail && detail !== base.text ? `${base.text}：${detail}` : base.text,
    }
  }
  return { text: detail || '请求失败，请稍后重试', hint: undefined }
}
