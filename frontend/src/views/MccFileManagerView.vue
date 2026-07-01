<template>
  <div class="file-page">
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">MCC FILES</h2>
        <div class="mono page-subtitle">
          {{ instanceLabel }} · {{ instance?.status || 'loading' }} · {{ instance?.instance_dir || '--' }}
        </div>
      </div>
      <div class="header-actions">
        <router-link to="/mcc/instances" class="pixel-btn outline page-link">返回实例</router-link>
        <button class="pixel-btn outline" @click="refreshPage">刷新</button>
        <button class="pixel-btn" :disabled="!instance || instance.status === 'running' || isBusy" @click="startInstance">启动</button>
        <button class="pixel-btn warning" :disabled="!instance || instance.status !== 'running' || isBusy" @click="stopInstance">停止</button>
      </div>
    </div>

    <div v-if="instance" class="pixel-card">
      <div class="meta-line mono">
        <span>PID: {{ instance.pid || '--' }}</span>
        <span>账号: {{ instance.mc_username || '--' }}</span>
        <span>服务器: {{ serverLabel }}</span>
      </div>
      <MccFileManagerPanel :instance-id="instance.instance_id" :slug="instance.slug" />
    </div>

    <div v-else class="pixel-card empty-state mono">-- 正在加载 --</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import MccFileManagerPanel from '@/components/MccFileManagerPanel.vue'
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

async function refreshPage() {
  await store.fetchInstances()
}

async function startInstance() {
  if (!instance.value) return
  try {
    await store.startInstance(instance.value.instance_id)
    ElMessage.success('启动命令已发送')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '启动失败')
  }
}

async function stopInstance() {
  if (!instance.value) return
  await store.stopInstance(instance.value.instance_id)
  ElMessage.success('停止命令已发送')
}

onMounted(() => store.fetchInstances())
</script>

<style scoped>
.file-page { display: flex; flex-direction: column; gap: 18px; min-height: 100%; }
.page-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 8px; }
.page-subtitle { color: var(--text-secondary); font-size: 14px; max-width: 860px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.header-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.page-link { text-decoration: none; display: inline-flex; align-items: center; }
.meta-line { display: flex; gap: 20px; color: var(--text-secondary); font-size: 13px; margin-bottom: 12px; }
.empty-state { color: var(--text-muted); text-align: center; padding: 80px 0; }
.pixel-btn:disabled { opacity: .45; cursor: not-allowed; }
</style>
