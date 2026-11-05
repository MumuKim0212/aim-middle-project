import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 중 /api 요청은 FastAPI(8000)로 넘긴다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
