import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 개발 중 /api 요청은 FastAPI 로 넘긴다. 기본은 8000, 다른 포트를 쓰려면 API_PROXY 환경변수로 지정한다.
// 예) API_PROXY=http://127.0.0.1:8001 npm run dev
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: { '/api': env.API_PROXY || 'http://127.0.0.1:8000' },
    },
  }
})
