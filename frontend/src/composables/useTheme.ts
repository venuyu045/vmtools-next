/**
 * 主题管理（Anthropic 风格双模式）
 * - localStorage['vmtools-theme'] = 'light' | 'dark' | 'system'
 * - 防闪白脚本（index.html）已按此 key 预设 data-theme，此处负责后续切换与系统跟随
 * - 联动逻辑：无手动选择（或无记录/异常值）→ 跟随系统；有手动选择 → 以手动为准
 * - 持久化：localStorage 记录用户手动选择，刷新后保留
 */
import { ref } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'vmtools-theme'

/** localStorage 只接受三态，异常值（旧值污染 / 手改 / 隐私模式）一律回落「跟随系统」 */
function readMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch { /* 隐私模式等异常场景 */ }
  return 'system'
}

/** 读取系统深色偏好（异常环境兜底 false） */
function systemPrefersDark(): boolean {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch {
    return false
  }
}

/** 从 html[data-theme] 读取当前生效主题（防闪白脚本已设有效值 light|dark；异常值按系统偏好兜底） */
function readResolved(): 'light' | 'dark' {
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr === 'dark' || attr === 'light') return attr
  return systemPrefersDark() ? 'dark' : 'light'
}

/** 当前选择模式（持久化） */
const mode = ref<ThemeMode>(readMode())
/** 实际生效主题 */
const resolved = ref<'light' | 'dark'>(readResolved())

function apply() {
  const dark = mode.value === 'dark' || (mode.value === 'system' && systemPrefersDark())
  resolved.value = dark ? 'dark' : 'light'
  const root = document.documentElement
  root.setAttribute('data-theme', resolved.value)
  // EP 暗色 css-vars.css 只认 html.dark，需与 data-theme 同步挂 class（global.css 双选择器兼容）
  root.classList.toggle('dark', dark)
  // 浏览器地址栏/状态栏颜色随主题切换（亮=暖米 / 暗=暖墨）
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) meta.content = dark ? '#1A1916' : '#ECE9E0'
}

/** 设置模式并持久化 */
export function setThemeMode(m: ThemeMode) {
  mode.value = m
  try { localStorage.setItem(STORAGE_KEY, m) } catch { /* 隐私模式等异常场景，忽略持久化 */ }
  apply()
}

/** 快速切换亮/暗（顶栏按钮用） */
export function toggleTheme() {
  setThemeMode(resolved.value === 'dark' ? 'light' : 'dark')
}

/** 系统主题变化时，system 模式下自动跟随（兼容旧版 Safari addListener） */
const media = window.matchMedia('(prefers-color-scheme: dark)')
if (typeof media.addEventListener === 'function') {
  media.addEventListener('change', () => { if (mode.value === 'system') apply() })
} else if (typeof (media as any).addListener === 'function') {
  ;(media as any).addListener(() => { if (mode.value === 'system') apply() })
}

// 初始化：与防闪白脚本结果对齐（确保 localStorage 异常场景下状态一致）
apply()

export function useTheme() {
  return { mode, resolved, setThemeMode, toggleTheme }
}