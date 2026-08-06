import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

export default defineConfig({
  plugins: [
    vue(),
    {
      // 构建前只清理旧的 assets 产物，不清空整个 static 目录
      // （历史事故：emptyOutDir:true 曾删掉 item-icons 296 张图标等非构建产物）
      name: 'clean-static-assets',
      buildStart() {
        const assetsDir = path.resolve(__dirname, '../backend/static/assets')
        if (fs.existsSync(assetsDir)) {
          fs.rmSync(assetsDir, { recursive: true, force: true })
        }
      },
    },
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://localhost:8080',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: process.env.VITE_OUT_DIR || path.resolve(__dirname, '../backend/static'),
    // 不再清空整个 static 目录（item-icons 等非构建产物会被误删）
    emptyOutDir: false,
  },
  base: '/static/',
})
