/**
 * 统一错误信息转换（2026-08-13 汉化）
 *
 * 把 AxiosError / Error 转换为友好的中文提示，避免前端到处泄漏
 * `AxiosError: Request failed with status code 500` 等英文原始对象。
 *
 * 优先级：
 * 1. 后端返回的 detail（HTTP 4xx 业务错误，后端已是中文，直接透传）
 * 2. HTTP 状态码级通用提示（401/403/404/400/5xx…）
 * 3. 网络层错误（无响应 / 超时）
 * 4. 调用方传入的 fallback（默认「操作失败，请稍后重试」）
 *
 * 用法：catch (e) { ElMessage.error(errMsg(e, '自定义兜底文案')) }
 */
import type { AxiosError } from 'axios'

export function errMsg(e: unknown, fallback = '操作失败，请稍后重试'): string {
  const err = e as AxiosError<{ detail?: unknown }> | undefined

  // 后端业务错误 detail 优先透传（后端已是中文）
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail

  // HTTP 状态码级通用提示
  const status = err?.response?.status
  switch (status) {
    case 401: return '登录已过期，请重新登录'
    case 403: return '没有权限执行此操作'
    case 404: return '请求的资源不存在'
    case 400: return '请求参数有误，请检查后重试'
    case 408: return '请求超时，请重试'
    case 413: return '上传内容过大，请压缩后重试'
    case 422: return '提交的数据格式有误，请检查后重试'
    case 429: return '操作过于频繁，请稍后再试'
    case 500: return '服务器内部错误，请稍后重试'
    case 502: return '网关错误，请稍后重试'
    case 503: return '服务暂时不可用，请稍后重试'
    case 504: return '网关响应超时，请稍后重试'
  }

  // 网络层错误（axios 主动取消不提示，静默）
  if (err?.code === 'ECONNABORTED') return '请求超时，请检查网络后重试'
  if (err?.code === 'ERR_CANCELED') return fallback
  if (!err?.response && err?.request) return '网络连接失败，请检查网络'
  if (err?.message && err.message !== 'Network Error' && !err.message.startsWith('Request failed')) {
    return err.message
  }

  return fallback
}

/** 取后端 detail（用于不需要完整转换、只想拿 detail 的场景） */
export function apiDetail(e: unknown): string {
  const err = e as AxiosError<{ detail?: unknown }> | undefined
  const detail = err?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : ''
}
