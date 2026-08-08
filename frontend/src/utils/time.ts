/**
 * 统一时间解析/格式化工具
 *
 * 后端约定：所有时间用 `datetime.now(timezone.utc)`（UTC）写入；
 * SQLite 无时区类型，读回后丢失 tzinfo → API 返回无时区字符串（naive UTC，
 * 形如 "2026-08-08T10:30:00"）。
 *
 * 若前端直接 `new Date(naive)`，浏览器会按本地时区（UTC+8）解释，
 * 导致显示比北京时间慢 8 小时。这里统一处理：无时区后缀 → 补 'Z' 按 UTC 解析。
 */
export function parseApiDate(s: string | number | null | undefined): Date | null {
  if (s == null || s === '') return null
  // 数字 = epoch 毫秒（无时区概念），直接构造
  if (typeof s === 'number') {
    const d = new Date(s)
    return Number.isNaN(d.getTime()) ? null : d
  }
  // 字符串：带时区后缀（Z / +08:00）直接解析；否则视为 naive UTC，补 'Z'
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(s) ? s : s + 'Z'
  const d = new Date(normalized)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 按浏览器本地时区格式化后端时间（naive UTC 自动转本地）。 */
export function fmtApiTime(
  s: string | number | null | undefined,
  opts: Intl.DateTimeFormatOptions = {},
): string {
  const d = parseApiDate(s)
  if (!d) return '—'
  return d.toLocaleString('zh-CN', { hour12: false, ...opts })
}
