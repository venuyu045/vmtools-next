<template>
  <div class="bot-status-page">
    <div class="page-header">
      <h2 class="page-title">> {{ title }}</h2>
      <div class="header-actions">
        <span v-if="lastUpdate" class="update-hint">更新于 {{ lastUpdate }}</span>
        <button class="refresh-btn" :disabled="loading" @click="load">⟳ 刷新</button>
      </div>
    </div>

    <div v-if="loading && !items.length" class="empty">加载中…</div>
    <div v-else-if="!items.length" class="empty">暂无 {{ engineLabel }} bot（可前往对应管理页添加）</div>

    <div class="card-grid">
      <div
        v-for="bot in items"
        :key="bot.bot_id"
        class="bot-card"
        :class="'status-' + bot.status"
      >
        <div class="card-head">
          <span class="bot-name">{{ bot.name }}</span>
          <span class="bot-id">{{ bot.bot_id }}</span>
          <span class="status-badge" :class="bot.status">{{ statusLabel(bot.status) }}</span>
        </div>

        <div class="vitals">
          <div class="vital">
            <span class="vital-label">❤ 血量</span>
            <div class="bar">
              <div class="bar-fill health" :style="{ width: healthPct(bot) }" />
            </div>
            <span class="vital-val">{{ bot.current_health != null ? bot.current_health + ' / 20' : '—' }}</span>
          </div>
          <div class="vital">
            <span class="vital-label">🍗 饱食度</span>
            <div class="bar">
              <div class="bar-fill food" :style="{ width: foodPct(bot) }" />
            </div>
            <span class="vital-val">{{ bot.current_food != null ? bot.current_food + ' / 20' : '—' }}</span>
          </div>
        </div>

        <div class="info-rows">
          <div class="info-row">
            <span class="info-label">当前工作</span>
            <span v-if="bot.current_task" class="info-val">
              <span class="task-type" :class="bot.current_task.type">{{ taskTypeLabel(bot.current_task.type) }}</span>
              {{ bot.current_task.name }}
              <span v-if="bot.current_task.progress != null" class="dist">（{{ bot.current_task.progress }}%）</span>
            </span>
            <span v-else class="info-val idle">空闲</span>
          </div>
          <div class="info-row">
            <span class="info-label">坐标</span>
            <span class="info-val">{{ coordText(bot) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">最近领地</span>
            <span v-if="bot.nearest_residence" class="info-val">
              {{ bot.nearest_residence.label }}
              <span class="dim">（{{ bot.nearest_residence.owner }}）</span>
              <span class="dist">· {{ bot.nearest_residence.distance }} 格</span>
            </span>
            <span v-else class="info-val dim">—</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import api from '@/api/client'
import { useSocketIO } from '@/composables/useSocketIO'

defineOptions({ name: 'BotStatusView' })

const props = defineProps<{
  engine?: string
  title?: string
}>()

const engine = computed(() => props.engine || 'mcc')
const title = computed(() => props.title || (engine.value === 'mineflayer' ? 'MF 状态' : 'MCC 状态'))
const engineLabel = computed(() => (engine.value === 'mineflayer' ? 'MF' : 'MCC'))

interface NearestResidence {
  label: string
  owner: string
  world: string
  distance: number
  position: { x?: number; y?: number; z?: number }
}

interface BotCurrentTask {
  type: string
  name: string
  status: string
  progress: number | null
}

interface BotStatus {
  bot_id: string
  name: string
  status: string
  mc_username: string
  current_health: number | null
  current_food: number | null
  current_location: { x?: number; y?: number; z?: number } | null
  nearest_residence: NearestResidence | null
  current_task: BotCurrentTask | null
}

const items = ref<BotStatus[]>([])
const loading = ref(false)
const lastUpdate = ref('')
let timer: number | undefined
// 请求竞态保护：只采纳最新一次请求的响应（切页/切引擎时旧请求不覆盖新数据）
let loadSeq = 0

// Socket.IO：启停/心跳等 bot 状态变化就地更新卡片，无需等 10s 轮询
const { on, off } = useSocketIO()

function patchBotStatus(payload: any) {
  if (!payload?.bot_id) return
  const idx = items.value.findIndex(b => b.bot_id === payload.bot_id)
  if (idx < 0) return
  const cur = items.value[idx]
  const next: BotStatus = { ...cur }
  if (payload.status) next.status = payload.status
  if (payload.current_health != null) next.current_health = payload.current_health
  if (payload.current_food != null) next.current_food = payload.current_food
  if (payload.current_location) next.current_location = payload.current_location
  items.value[idx] = next
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    online: '在线',
    offline: '离线',
    error: '异常',
    starting: '启动中',
  }
  return map[s] || s
}

function taskTypeLabel(t: string): string {
  const map: Record<string, string> = {
    logistics: '物流',
    mapart: '地图画',
    scan: '扫描',
  }
  return map[t] || t
}

function healthPct(bot: BotStatus): string {
  if (bot.current_health == null) return '0%'
  return Math.max(0, Math.min(100, (bot.current_health / 20) * 100)) + '%'
}

function foodPct(bot: BotStatus): string {
  if (bot.current_food == null) return '0%'
  return Math.max(0, Math.min(100, (bot.current_food / 20) * 100)) + '%'
}

function coordText(bot: BotStatus): string {
  const loc = bot.current_location
  if (!loc || loc.x == null || loc.z == null) return '—'
  return `x ${Math.round(loc.x)}  y ${loc.y != null ? Math.round(loc.y) : '?'}  z ${Math.round(loc.z)}`
}

async function load() {
  if (loading.value) return
  const seq = ++loadSeq
  loading.value = true
  try {
    const resp = await api.get(`/mcc-bots/status/overview?engine=${engine.value}`)
    if (seq !== loadSeq) return // 过期响应（已切引擎/新请求发出）丢弃
    items.value = resp.data?.items || []
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    /* 静默失败，保留旧数据 */
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function onBotStatusUpdate(payload: any) { patchBotStatus(payload) }
function onBotConnected(payload: any) { patchBotStatus({ bot_id: payload.bot_id, status: 'online' }) }
function onBotDisconnected(payload: any) { patchBotStatus({ bot_id: payload.bot_id, status: 'offline' }) }

onMounted(() => {
  load()
  timer = window.setInterval(load, 10000)
  // Socket.IO 订阅（keep-alive 下组件常驻，onMounted 只执行一次）
  on('bot_status_update', onBotStatusUpdate)
  on('bot_connected', onBotConnected)
  on('bot_disconnected', onBotDisconnected)
})

// keep-alive 下：切走暂停轮询（省请求），切回立即刷新并恢复轮询
onActivated(() => {
  load()
  if (!timer) timer = window.setInterval(load, 10000)
})

onDeactivated(() => {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
})

// MCC ↔ MF 状态切换：同一组件复用（keep-alive 下不重新挂载），
// engine prop 变化时立即重新加载，避免等 10s 定时器或手动刷新；
// 同时使在途请求失效并允许新请求立即发出。
watch(() => props.engine, () => {
  loadSeq++
  loading.value = false
  items.value = []
  load()
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  off('bot_status_update', onBotStatusUpdate)
  off('bot_connected', onBotConnected)
  off('bot_disconnected', onBotDisconnected)
})
</script>

<style scoped>
.bot-status-page {
  padding: 4px 2px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
  gap: 12px;
  flex-wrap: wrap;
}

.page-title {
  font-family: var(--font-pixel);
  font-size: 16px;
  color: var(--green-primary);
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.update-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.refresh-btn {
  background: none;
  border: 1px solid var(--border-card);
  color: var(--green-primary);
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-body);
}

.refresh-btn:hover {
  border-color: var(--border-active);
  background: var(--green-glow);
  color: var(--text-primary);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.empty {
  padding: 60px 0;
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.bot-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.bot-card.status-online {
  border-left: 3px solid #4caf50;
}

.bot-card.status-error,
.bot-card.status-crashed {
  border-left: 3px solid #f44336;
}

.bot-card.status-offline {
  border-left: 3px solid #555;
}

.bot-card.status-starting {
  border-left: 3px solid #ff9800;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bot-name {
  font-size: 16px;
  color: var(--text-primary);
  font-weight: 600;
}

.bot-id {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.status-badge {
  margin-left: auto;
  font-size: 11px;
  padding: 3px 10px;
  border: 1px solid var(--border-card);
  font-family: var(--font-mono);
  letter-spacing: 1px;
}

.status-badge.online {
  color: #4caf50;
  border-color: #4caf50;
}

.status-badge.offline {
  color: #888;
}

.status-badge.error,
.status-badge.crashed {
  color: #f44336;
  border-color: #f44336;
}

.status-badge.starting {
  color: #ff9800;
  border-color: #ff9800;
}

.vitals {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vital {
  display: flex;
  align-items: center;
  gap: 10px;
}

.vital-label {
  width: 64px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.bar {
  flex: 1;
  height: 8px;
  background: #1a1a1a;
  border: 1px solid var(--border-card);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  transition: width 0.4s ease;
}

.bar-fill.health {
  background: #f44336;
}

.bar-fill.food {
  background: #ff9800;
}

.vital-val {
  width: 56px;
  flex-shrink: 0;
  text-align: right;
  font-size: 12px;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.info-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 10px;
}

.info-row {
  display: flex;
  gap: 10px;
  font-size: 12px;
}

.info-label {
  width: 64px;
  flex-shrink: 0;
  color: var(--text-muted);
}

.info-val {
  color: var(--text-secondary);
  word-break: break-all;
}

.idle {
  color: #4caf50;
}

.task-type {
  display: inline-block;
  padding: 1px 6px;
  margin-right: 6px;
  font-size: 11px;
  border: 1px solid var(--border-card);
  font-family: var(--font-mono);
}

.task-type.logistics {
  color: #42a5f5;
  border-color: #42a5f5;
}

.task-type.mapart {
  color: #ab47bc;
  border-color: #ab47bc;
}

.task-type.scan {
  color: #ffa726;
  border-color: #ffa726;
}

.dim {
  color: var(--text-muted);
}

.dist {
  color: var(--green-primary);
}
</style>