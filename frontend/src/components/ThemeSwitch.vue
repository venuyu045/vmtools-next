<template>
  <button
    class="theme-switch-btn"
    :title="title"
    :aria-label="title"
    @click="cycle"
  >
    <span class="ts-icon">◐</span>
    <span class="ts-text">{{ label }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTheme, type ThemeMode } from '@/composables/useTheme'

const { mode, resolved, setThemeMode } = useTheme()

/** 三态循环：跟随系统 → 亮色 → 暗色 → 跟随系统（登录/注册页无下拉面板，循环足够） */
const ORDER: ThemeMode[] = ['system', 'light', 'dark']

const label = computed(() => {
  if (mode.value === 'system') return '跟随'
  return resolved.value === 'dark' ? '暗色' : '亮色'
})

const title = computed(() => {
  const cur = mode.value === 'system'
    ? `跟随系统（当前${resolved.value === 'dark' ? '暗色' : '亮色'}）`
    : (resolved.value === 'dark' ? '暗色' : '亮色')
  return `主题：${cur}，点击切换`
})

function cycle() {
  const next = ORDER[(ORDER.indexOf(mode.value) + 1) % ORDER.length]
  setThemeMode(next)
}
</script>

<style scoped>
.theme-switch-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: border-color 150ms var(--ease-out), color 150ms var(--ease-out), background-color 150ms var(--ease-out);
}
.theme-switch-btn:hover {
  border-color: var(--accent);
  color: var(--text-primary);
  background: var(--bg-hover);
}
.ts-icon { font-size: 14px; line-height: 1; }
.ts-text { white-space: nowrap; }
</style>