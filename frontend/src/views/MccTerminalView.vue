<template>
  <div class="terminal-page">
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">MCC TERMINAL</h2>
        <div class="mono page-subtitle">
          {{ instanceLabel }} · {{ instance?.status || 'loading' }} · {{ instance?.instance_dir || '--' }}
        </div>
      </div>
      <div class="header-actions">
        <router-link to="/bots" class="pixel-btn outline terminal-link">返回实例</router-link>
        <button class="pixel-btn outline" @click="refreshInstance">刷新</button>
        <button class="pixel-btn" :disabled="!instance || instance.status === 'running' || isBusy" @click="startInstance">启动</button>
        <button class="pixel-btn warning" :disabled="!instance || instance.status !== 'running' || isBusy" @click="stopInstance">停止</button>
      </div>
    </div>

    <div v-if="instance" class="pixel-card terminal-card">
      <div class="terminal-meta mono">
        <span>PID: {{ instance.pid || '--' }}</span>
        <span>MCP: {{ instance.mcp_host }}:{{ instance.mcp_port }}</span>
        <span>账号: {{ instance.mc_username || '--' }}</span>
        <span>服务器: {{ serverLabel }}</span>
      </div>
      <MccWebTerminal
        :instance-id="instance.instance_id"
        :slug="instance.slug"
        :title="instance.display_name || instance.slug"
        height="calc(100vh - 300px)"
      />
    </div>

    <div v-else class="pixel-card empty-state mono">
      -- 正在加载 MCC 实例，或实例不存在 --
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import MccWebTerminal from '@/components/MccWebTerminal.vue'
import { useMccInstanceStore } from '@/stores/mccInstance'

const route = useRoute()
const store = useMccInstanceStore()
const instanceId = computed(() => String(route.params.id || ''))
const instance = computed(() => store.instances.find(item => item.instance_id === instanceId.value) || null)
const isBusy = computed(() => instance.value ? !!store.actionLoading[instance.value.instance_id] : false)
const instanceLabel = computed(() => instance.value ? `${instance.value.display_name || instance.value.slug}` : instanceId.value)
const serverLabel = computed(() => {
  if (!instance.value?.mc_server_host) return '--'
  return `${instance.value.mc_server_host}:${instance.value.mc_server_port}`
})

async function refreshInstance() {
  await store.fetchInstances()
  if (instance.value) await store.fetchTerminalHistory(instance.value.instance_id)
}

async function startInstance() {
  if (!instance.value) return
  try {
    await store.startInstance(instance.value.instance_id)
    await store.fetchTerminalHistory(instance.value.instance_id)
    ElMessage.success('启动命令已发送')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '启动失败，请检查 MCC 程序路径')
  }
}

async function stopInstance() {
  if (!instance.value) return
  await store.stopInstance(instance.value.instance_id)
  ElMessage.success('停止命令已发送')
}

onMounted(() => refreshInstance())
</script>

<style scoped>
.terminal-page { display: flex; flex-direction: column; gap: 18px; min-height: 100%; }
.page-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 8px; }
.page-subtitle { color: var(--text-secondary); font-size: 14px; max-width: 860px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.header-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.terminal-link { text-decoration: none; display: inline-flex; align-items: center; }
.terminal-card { display: flex; flex-direction: column; gap: 12px; min-height: calc(100vh - 210px); }
.terminal-meta { display: flex; flex-wrap: wrap; gap: 18px; color: var(--text-secondary); font-size: 13px; }
.empty-state { color: var(--text-muted); text-align: center; padding: 80px 0; }
.pixel-btn:disabled { opacity: .45; cursor: not-allowed; }

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .terminal-page { gap: 12px; }
  .page-header { flex-direction: column; gap: 10px; }
  .page-title { font-size: 14px; }
  .page-subtitle { font-size: 12px; max-width: 100%; }
  .header-actions .pixel-btn { font-size: 12px; padding: 6px 10px; }
  .terminal-meta { font-size: 11px; gap: 10px; }
  .terminal-card { min-height: calc(100dvh - 200px); }
}
</style>
