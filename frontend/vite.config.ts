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
      // 注意：必须跟随实际 outDir；否则用 VITE_OUT_DIR 指到别处时仍会误删后端产物。
      name: 'clean-static-assets',
      // ⚠️ 只在 build 阶段生效：`npm run dev` 同样会触发 buildStart，
      // 而 dev 不会产出新文件 —— 结果是「跑一次开发服务器，就把已提交进 git 的
      // backend/static/assets 全删了」，工作区凭空多出一堆 D 状态。
      apply: 'build',
      buildStart() {
        const outDir = process.env.VITE_OUT_DIR
          ? path.resolve(process.env.VITE_OUT_DIR)
          : path.resolve(__dirname, '../backend/static')
        const assetsDir = path.join(outDir, 'assets')
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
