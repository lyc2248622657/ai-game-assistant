// vitest/config 的 defineConfig 才认识 `test` 字段（用 'vite' 会报 TS2769）
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// 开发环境将 /api 代理到后端 FastAPI（8000 端口）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
    // 用例只有 20 个左右：单进程跑更稳（默认多 worker 在低配/受限环境里
    // 偶发 "Worker exited unexpectedly"，会把整轮测试判成失败）
    pool: 'forks',
    poolOptions: { forks: { singleFork: true } },
  },
})
