/**
 * 数字展示格式化工具（统一供仪表盘 / 仓库管理 / 仓库状态等页面使用）
 *
 * 混合规则（已确认）：
 *   - 详细数据：fmtExact —— toLocaleString 精确值（如 30,000,000）
 *   - 大概数据：fmtBigNum —— ≥1亿 → x.x亿；≥1万 → x.x万（整数万显示整数，如 3000万）；
 *                            ≥1k → x.xk；<1k → 原始数字
 *   - 盒数：boxCount —— 数量 ÷ 1728（潜影盒 = 27 槽 × 64），保留 1 位小数
 */

/** 精确数字：千分位分隔（30,000,000） */
export function fmtExact(v: number | string | null | undefined): string {
  if (v == null || isNaN(Number(v))) return '0'
  return Number(v).toLocaleString('en-US')
}

/** 取整到 1 位小数，整数则去小数位 */
function trimNum(x: number): string {
  const r = Math.round(x * 10) / 10
  return Number.isInteger(r) ? String(Math.round(r)) : r.toFixed(1)
}

/** 大数字混合格式：≥1亿 → x.x亿；≥1万 → x.x万；≥1k → x.xk；<1k → 原数字 */
export function fmtBigNum(v: number | string | null | undefined): string {
  if (v == null || isNaN(Number(v))) return '0'
  const n = Number(v)
  const abs = Math.abs(n)
  if (abs >= 1e8) return trimNum(n / 1e8) + '亿'
  if (abs >= 1e4) return trimNum(n / 1e4) + '万'
  if (abs >= 1e3) return trimNum(n / 1e3) + 'k'
  return String(Math.round(n))
}

/** 盒数：数量 ÷ 1728，保留 1 位小数（1728 = 27 槽 × 64/潜影盒） */
export function boxCount(v: number | string | null | undefined): string {
  if (v == null || isNaN(Number(v))) return '0'
  return (Number(v) / 1728).toFixed(1)
}
