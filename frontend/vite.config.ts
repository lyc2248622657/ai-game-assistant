import { defineConfig } from 'vite'
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
})
