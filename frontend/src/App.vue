<template>
  <router-view />
</template>

<script setup lang="ts">
import { onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useSocketIO } from '@/composables/useSocketIO'

const authStore = useAuthStore()
const { connect, disconnect } = useSocketIO()

// 2026-10-15 审查修复：建连时机由 onMounted 提前到 setup 阶段。
// 原因：Vue 中【子组件的 onMounted 早于父组件 onMounted】执行 → 首屏直接落在
// 依赖 socket 的页面（如 /tasks、/mf-status）时，子组件注册 on() 的那一刻
// 模块级 socket 尚未创建（useSocketIO 内 `socket?.on` 静默无操作）→ 实时事件
// 监听永久丢失，页面只剩 30s 轮询兜底。放在 setup 可保证子组件挂载时已建连。
if (authStore.isLoggedIn) {
  authStore.getMe()
  connect()
}

// Watch for login/logout
watch(() => authStore.isLoggedIn, (loggedIn) => {
  if (loggedIn) {
    connect()
  } else {
    disconnect()
  }
})

onUnmounted(() => {
  disconnect()
})
</script>
