import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const basePath = env.VITE_BASE_PATH || (mode === 'production' ? '/mithrandir/' : '/')

  return {
    plugins: [react()],
    base: basePath,
    server: {
      proxy: {
        '/api': { target: 'http://localhost:8000', changeOrigin: true },
        '/ws':  { target: 'ws://localhost:8000',  ws: true },
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
