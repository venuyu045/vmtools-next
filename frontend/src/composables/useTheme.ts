/**
 * 主题管理（Anthropic 风格双模式）
 * - localStorage['vmtools-theme'] = 'light' | 'dark' | 'system'
 * - 防闪白脚本（index.html）已按此 key 预设 data-theme，此处负责后续切换与系统跟随
 */
import { ref } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'vmtools-theme'
const media = window.matchMedia('(prefers-color-scheme: dark)')

/** 当前选择模式（持久化） */
const mode = ref<ThemeMode>((localStorage.getItem(STORAGE_KEY) as ThemeMode) || 'system')
/** 实际生效主题 */
const resolved = ref<'light' | 'dark'>(
  document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
)

function apply() {
  const dark = mode.value === 'dark' || (mode.value === 'system' && media.matches)
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
  localStorage.setItem(STORAGE_KEY, m)
  apply()
}

/** 快速切换亮/暗（顶栏按钮用） */
export function toggleTheme() {
  setThemeMode(resolved.value === 'dark' ? 'light' : 'dark')
}

/** 系统主题变化时，system 模式下自动跟随 */
media.addEventListener('change', () => {
  if (mode.value === 'system') apply()
})

// 初始化：与防闪白脚本结果对齐（确保 localStorage 异常场景下状态一致）
apply()

export function useTheme() {
  return { mode, resolved, setThemeMode, toggleTheme }
}
