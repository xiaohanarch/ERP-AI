import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// VITE_GW_BASE / VITE_HUB_BASE 由构建参数注入（Dockerfile ARG -> ENV），
// 开发模式下回落到本机默认端口。
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
