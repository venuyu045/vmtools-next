<template>
  <div v-if="visible" class="dev-console" :class="{ collapsed }">
    <div class="dev-toolbar" @click="collapsed = !collapsed">
      <span class="dev-title mono">[DEV] 调试控制台</span>
      <span class="dev-count">{{ logs.length }} 条</span>
      <div class="dev-actions">
        <select v-model="filter" class="dev-filter" @click.stop>
          <option value="all">全部</option>
          <option value="socket">Socket.IO</option>
          <option value="mcc">MCC</option>
          <option value="api">API</option>
          <option value="error">错误</option>
        </select>
        <button class="pixel-btn outline" @click.stop="clearLogs">清空</button>
        <button class="pixel-btn outline" @click.stop="visible = false">关闭</button>
      </div>
    </div>
    <div v-if="!collapsed" ref="logContainer" class="dev-logs">
      <div
        v-for="(log, index) in filteredLogs"
        :key="index"
        class="dev-line mono"
        :class="'level-' + log.level"
      >
        <span class="dev-time">{{ formatTime(log.ts) }}</span>
        <span class="dev-tag">{{ log.tag }}</span>
        <span class="dev-msg">{{ log.msg }}</span>
      </div>
      <div v-if="filteredLogs.length === 0" class="dev-empty">无日志</div>
    </div>
  </div>
  <button
    v-else
    class="dev-toggle pixel-btn outline"
    @click="visible = true"
  >
    [DEV]
  </button>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useDevLogStore } from '@/stores/devLog'
import { useSocketIO } from '@/composables/useSocketIO'

const store = useDevLogStore()
const socket = useSocketIO()
const visible = ref(false)
const collapsed = ref(false)
const filter = ref('all')
const logContainer = ref<HTMLElement | null>(null)

const logs = computed(() => store.logs)
const filteredLogs = computed(() => {
  if (filter.value === 'all') return logs.value
  return logs.value.filter(l => l.tag.includes(filter.value))
})

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

function clearLogs() {
  store.clear()
}

watch(filteredLogs, async () => {
  await nextTick()
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
})

// Hook Socket.IO events for debug logging
onMounted(() => {
  const rawSocket = socket.getSocket()
  if (rawSocket) {
    rawSocket.on('connect', () => store.log('socket', 'Socket.IO 已连接', 'info'))
    rawSocket.on('disconnect', (reason: string) => store.log('socket', `Socket.IO 断开: ${reason}`, 'warn'))
    rawSocket.on('connect_error', (err: any) => store.log('socket', `Socket.IO 连接错误: ${err?.message || err}`, 'error'))
    rawSocket.on('mcc_instance_status', (p: any) =>
      store.log('mcc', `实例状态: ${p.instance_id?.slice(0,8)} → ${p.status} (pid=${p.pid})`, 'info'))
    rawSocket.on('mcc_terminal_output', (p: any) =>
      store.log('mcc', `终端[${p.stream}]: ${(p.content||'').slice(0,60)}`, 'info'))
    rawSocket.on('mcc_terminal_error', (p: any) =>
      store.log('mcc', `终端错误: ${p.message}`, 'error'))
  }
})

// Ctrl+Shift+D to toggle
function onKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && e.shiftKey && e.key === 'D') {
    visible.value = !visible.value
  }
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.dev-console {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 9999;
  background: #0a0a0a; border-top: 2px solid var(--green-primary);
  max-height: 45vh; display: flex; flex-direction: column;
}
.dev-console.collapsed { max-height: 36px; }
.dev-toolbar {
  display: flex; align-items: center; gap: 12px;
  padding: 6px 16px; background: #111; cursor: pointer;
  border-bottom: 1px solid #222; user-select: none;
}
.dev-title { color: var(--green-primary); font-weight: bold; font-size: 13px; }
.dev-count { color: var(--text-muted); font-size: 12px; }
.dev-actions { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.dev-filter { font-size: 12px; padding: 2px 6px; background: #000; color: var(--green-primary); border: 1px solid #333; }
.dev-logs {
  flex: 1; overflow-y: auto; padding: 4px 0;
  background: #050505;
}
.dev-line {
  display: flex; gap: 8px; padding: 2px 16px; font-size: 11px; line-height: 1.5;
  border-bottom: 1px solid #0f0f0f;
}
.dev-line:hover { background: rgba(0,255,65,0.03); }
.dev-time { color: #555; min-width: 72px; }
.dev-tag {
  color: var(--green-primary); min-width: 50px; text-align: center;
  background: rgba(0,255,65,0.08); border-radius: 2px; padding: 0 4px; font-size: 10px;
}
.dev-msg { color: #ddd; flex: 1; word-break: break-all; }
.dev-line.level-warn .dev-msg { color: #ffcc00; }
.dev-line.level-error .dev-msg { color: #ff4d4f; }
.dev-line.level-warn .dev-tag { background: rgba(255,200,0,0.15); color: #ffcc00; }
.dev-line.level-error .dev-tag { background: rgba(255,0,0,0.15); color: #ff4d4f; }
.dev-empty { color: #444; padding: 12px 16px; font-size: 12px; }
.dev-toggle {
  position: fixed; bottom: 8px; right: 8px; z-index: 9998;
  padding: 4px 10px; font-size: 11px;
}
</style>
