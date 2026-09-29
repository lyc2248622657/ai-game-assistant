import { useEffect, useState } from 'react'
import { api } from '../api/client'

/** 应用内设置弹窗：填写 DeepSeek API Key + 模型类型（保存后即时生效，无需重启） */
export function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('deepseek-chat')
  const [status, setStatus] = useState<{ configured: boolean; source?: string | null; masked?: string }>({
    configured: false,
  })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // 打开时读取当前配置状态（只返回打码）
  useEffect(() => {
    if (!open) return
    api.getKeyStatus().then((s) => {
      setStatus({ configured: s.configured, source: s.source, masked: s.masked_key })
      if (s.model) setModel(s.model)
    })
  }, [open])

  if (!open) return null

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setMsg({ ok: false, text: '请填写 API Key（sk- 开头）' })
      return
    }
    setSaving(true)
    setMsg(null)
    try {
      const r = await api.saveKey(apiKey.trim(), model)
      setStatus({ configured: true, source: 'app_settings', masked: r.masked_key })
      setApiKey('')
      setMsg({ ok: true, text: r.message })
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    if (!apiKey.trim()) {
      setMsg({ ok: false, text: '请填写 API Key（sk- 开头）' })
      return
    }
    setTesting(true)
    setMsg(null)
    try {
      const r = await api.testKey(apiKey.trim(), model)
      setMsg({ ok: r.ok, text: r.message })
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }

  const sourceLabel = status.source === 'app_settings' ? '应用内设置' : status.source === 'env_or_file' ? '本地文件/环境变量' : ''

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[420px] rounded-xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-800">⚙ 模型设置</h2>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        {/* 当前状态 */}
        <div className="mb-4 rounded-lg bg-gray-50 px-3 py-2 text-xs">
          {status.configured ? (
            <span className="text-green-600">
              ✓ 已配置（{sourceLabel}）：<code className="font-mono">{status.masked}</code>
              {status.source === 'env_or_file' ? ' · 可在此覆盖为应用内设置' : ''}
            </span>
          ) : (
            <span className="text-amber-600">未配置 API Key —— 填写并保存后即可使用（无需重启）</span>
          )}
        </div>

        <label className="mb-1 block text-xs font-medium text-gray-600">DeepSeek API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-..."
          autoComplete="off"
          className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-400"
        />

        <label className="mb-1 block text-xs font-medium text-gray-600">模型类型</label>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-400"
        >
          <option value="deepseek-chat">deepseek-chat（通用对话，快）</option>
          <option value="deepseek-reasoner">deepseek-reasoner（深度推理，慢）</option>
        </select>

        {msg && (
          <div
            className={`mb-3 rounded-lg px-3 py-2 text-xs ${
              msg.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
            }`}
          >
            {msg.text}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={handleTest}
            disabled={testing}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            {testing ? '测试中…' : '测试连接'}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-blue-500 px-4 py-1.5 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
