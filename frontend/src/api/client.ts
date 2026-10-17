import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const client = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // 2026-10-15 审查修复：仅在【确实持有 token】（曾登录、token 失效）时才执行
      // 「清 token + 提示过期 + 跳登录」。原逻辑对所有 401 一律处理，导致未登录访客
      // 访问 guestReadable 只读页（任务中心 / 仪表盘等）时，本应「静默留白」的 401
      // 被误报为「登录已过期」并强制跳转登录页 → 访客只读浏览功能失效。
      const hadToken = !!localStorage.getItem('token')
      if (hadToken) {
        localStorage.removeItem('token')
        ElMessage.error('登录已过期，请重新登录')
        router.push('/login')
      }
      // 无 token（访客）：不提示、不跳转，交由调用方静默处理
    }
    return Promise.reject(error)
  }
)

export default client
