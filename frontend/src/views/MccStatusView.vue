<template>
  <div class="mcc-status-page">
    <div class="page-header">
      <h2 class="page-title">> MCC 状态</h2>
      <div class="header-actions">
        <span v-if="lastUpdate" class="update-hint">更新于 {{ lastUpdate }}</span>
        <button class="refresh-btn" :disabled="loading" @click="load">⟳ 刷新</button>
      </div>
    </div>

    <div v-if="loading && !items.length" class="empty">加载中…</div>
    <div v-else-if="!items.length" class="empty">暂无 MCC bot（可前往 MCC 管理添加）</div>

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
          <div class="info-row">
            <span class="info-label">MCP 连接</span>
            <span class="info-val">
              <template v-if="bot.mcp_port">端口 {{ bot.mcp_port }}</template>
              <template v-else>—</template>
              <template v-if="bot.last_heartbeat"> · {{ timeAgo(bot.last_heartbeat) }}</template>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import api from '@/api/client'

interface NearestResidence {
  label: string
  owner: string
  world: string
  distance: number
  position: { x?: number; y?: number; z?: number }
}

interface MccBotStatus {
  bot_id: string
  name: string
  status: string
  mc_username: string
  current_health: number | null
  current_food: number | null
  current_location: { x?: number; y?: number; z?: number } | null
  mcp_port: number | null
  last_heartbeat: string | null
  nearest_residence: NearestResidence | null
}

const items = ref<MccBotStatus[]>([])
const loading = ref(false)
const lastUpdate = ref('')
let timer: number | undefined

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    online: '在线',
    offline: '离线',
    error: '异常',
    starting: '启动中',
  }
  return map[s] || s
}

function healthPct(bot: MccBotStatus): string {
  if (bot.current_health == null) return '0%'
  return Math.max(0, Math.min(100, (bot.current_health / 20) * 100)) + '%'
}

function foodPct(bot: MccBotStatus): string {
  if (bot.current_food == null) return '0%'
  return Math.max(0, Math.min(100, (bot.current_food / 20) * 100)) + '%'
}

function coordText(bot: MccBotStatus): string {
  const loc = bot.current_location
  if (!loc || loc.x == null || loc.z == null) return '—'
  return `x ${Math.round(loc.x)}  y ${loc.y != null ? Math.round(loc.y) : '?'}  z ${Math.round(loc.z)}`
}

function timeAgo(iso: string): string {
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return ''
  const sec = Math.floor((Date.now() - ts) / 1000)
  if (sec < 5) return '刚刚'
  if (sec < 60) return sec + ' 秒前'
  const min = Math.floor(sec / 60)
  if (min < 60) return min + ' 分钟前'
  return Math.floor(min / 60) + ' 小时前'
}

async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const resp = await api.get('/mcc-bots/status/overview')
    items.value = resp.data?.items || []
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    /* 静默失败，保留旧数据 */
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 10000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.mcc-status-page {
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
  background: #0d0d0d;
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

.dim {
  color: var(--text-muted);
}

.dist {
  color: var(--green-primary);
}
</style>
