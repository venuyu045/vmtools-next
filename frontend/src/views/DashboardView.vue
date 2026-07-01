<template>
  <div class="dashboard">
    <!-- Stats Row -->
    <div class="stats-row">
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(0,255,0,0.3)">
          <span class="stat-value" style="color: var(--green-primary)">{{ botStore.onlineCount }}</span>
        </div>
        <div>
          <div class="stat-label">在线 Bot</div>
          <div class="stat-sub">运行中</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(255,255,0,0.3)">
          <span class="stat-value" style="color: #ffff00">{{ warehouseStore.warehouses.length }}</span>
        </div>
        <div>
          <div class="stat-label">仓库数量</div>
          <div class="stat-sub">{{ totalItems }} 物品</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(24,144,255,0.3)">
          <span class="stat-value" style="color: #1890ff">{{ runningTasks }}</span>
        </div>
        <div>
          <div class="stat-label">建造任务</div>
          <div class="stat-sub">{{ runningTasks }} 运行中</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(255,0,0,0.3)">
          <span class="stat-value" style="color: #ff0000">{{ logisticsStore.runs?.length || 0 }}</span>
        </div>
        <div>
          <div class="stat-label">物流任务</div>
          <div class="stat-sub">待命</div>
        </div>
      </div>
    </div>

    <!-- Content Row -->
    <div class="content-row">
      <!-- Left: Quick actions + Build status -->
      <div class="left-col">
        <div class="pixel-card quick-actions">
          <h3 class="pixel section-title">快速操作</h3>
          <div class="action-btns">
            <button class="pixel-btn" @click="$router.push('/build')">新建任务</button>
            <button class="pixel-btn outline" @click="$router.push('/warehouses')">扫描仓库</button>
            <button class="pixel-btn outline" @click="$router.push('/build')">上传投影</button>
          </div>
        </div>
        <div class="pixel-card build-status">
          <div class="section-header">
            <h3 class="pixel section-title">建造状态</h3>
            <router-link to="/build" class="view-all mono">查看全部 ></router-link>
          </div>
          <div v-if="buildStore.tasks.length === 0" class="empty-text mono">-- 暂无任务 --</div>
          <div v-for="task in buildStore.tasks.slice(0, 2)" :key="task.task_id" class="task-row">
            <div class="task-info">
              <div class="task-name">{{ task.projection_name || task.task_id }}</div>
              <div class="task-meta mono">层: {{ task.current_layer }}/{{ task.total_layers }}</div>
              <div class="pixel-progress">
                <div class="pixel-progress-fill green" :style="{ width: taskPct(task) + '%' }"></div>
              </div>
            </div>
            <span class="pixel task-pct">{{ taskPct(task) }}%</span>
            <span :class="['pixel-badge', task.status === 'running' ? 'green' : 'yellow']">
              <span class="badge-dot"></span>
              {{ task.status === 'running' ? '运行中' : '已暂停' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Right: Alerts + Monitor -->
      <div class="right-col">
        <div class="pixel-card alerts-panel">
          <h3 class="pixel section-title">最近告警</h3>
          <div v-if="monitorStore.alerts.length === 0" class="empty-text mono">-- 暂无告警 --</div>
          <div v-for="(alert, i) in monitorStore.alerts.slice(0, 4)" :key="i" class="alert-row">
            <span :class="['status-dot', alert.severity || 'warning']"></span>
            <div class="alert-info">
              <div class="alert-text">{{ alert.name || alert.metric_name }}</div>
              <div class="alert-time mono">刚刚</div>
            </div>
          </div>
        </div>
        <div v-if="latestMetrics" class="pixel-card monitor-panel">
          <h3 class="pixel section-title">系统状态</h3>
          <div class="mon-row">
            <span class="mon-label">CPU</span>
            <span class="mono mon-val">{{ latestMetrics.cpu_percent.toFixed(1) }}%</span>
          </div>
          <div class="mon-row">
            <span class="mon-label">内存</span>
            <span class="mono mon-val" style="color: #ffff00">{{ latestMetrics.memory_percent.toFixed(1) }}% · {{ fmtGB(latestMetrics.memory_used) }} / {{ fmtGB(latestMetrics.memory_total) }} GB</span>
          </div>
          <div class="mon-row">
            <span class="mon-label">磁盘</span>
            <span class="mono mon-val">{{ latestMetrics.disk_percent.toFixed(1) }}% · {{ fmtGB(latestMetrics.disk_used) }} / {{ fmtGB(latestMetrics.disk_total) }} GB</span>
          </div>
          <div class="mon-row">
            <span class="mon-label">运行时间</span>
            <span class="mono mon-val">{{ uptime }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useBotStore } from '@/stores/bot'
import { useWarehouseStore } from '@/stores/warehouse'
import { useBuildStore } from '@/stores/build'
import { useMonitorStore } from '@/stores/monitor'
import { useLogisticsStore } from '@/stores/logistics'

const botStore = useBotStore()
const warehouseStore = useWarehouseStore()
const buildStore = useBuildStore()
const monitorStore = useMonitorStore()
const logisticsStore = useLogisticsStore()

const runningTasks = computed(() => buildStore.tasks.filter(t => t.status === 'running').length)
const totalItems = computed(() => warehouseStore.warehouses.reduce((sum, w) => sum + (w.total_items || 0), 0))
const latestMetrics = computed(() => monitorStore.metrics?.[monitorStore.metrics.length - 1])
const uptime = computed(() => {
  if (!latestMetrics.value) return '--'
  const s = (Date.now() / 1000 - latestMetrics.value.timestamp) || 0
  if (s < 60) return `${Math.floor(s)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  return `${d}d ${h}h`
})
function taskPct(task: any): number {
  return task.total_layers > 0 ? Math.round(task.current_layer / task.total_layers * 100) : 0
}
function fmtGB(bytes: number): string {
  if (!bytes) return '0'
  return (bytes / 1024 / 1024 / 1024).toFixed(1)
}

onMounted(async () => {
  await Promise.all([
    botStore.fetchBots(),
    warehouseStore.fetchWarehouses(),
    buildStore.fetchTasks(),
    monitorStore.fetchAlerts(),
    monitorStore.fetchMetrics(),
  ])
})
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 24px; }

.stats-row { display: flex; gap: 16px; }

.content-row { display: flex; gap: 24px; }
.left-col { flex: 1; display: flex; flex-direction: column; gap: 24px; }
.right-col { width: 360px; flex-shrink: 0; display: flex; flex-direction: column; gap: 24px; }

.section-title { font-size: 14px; color: var(--green-primary); margin-bottom: 16px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.section-header .section-title { margin-bottom: 0; }

.view-all { font-size: 14px; color: var(--green-primary); opacity: 0.6; text-decoration: none; }
.view-all:hover { opacity: 1; }

.action-btns { display: flex; gap: 12px; }

.empty-text { color: var(--text-muted); text-align: center; padding: 20px; font-size: 16px; }

/* Build task rows */
.task-row { display: flex; align-items: center; gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--border-subtle); }
.task-row:last-child { border-bottom: none; }
.task-info { flex: 1; }
.task-name { color: var(--text-primary); font-size: 14px; margin-bottom: 4px; font-weight: bold; }
.task-meta { color: var(--text-secondary); font-size: 14px; margin-bottom: 8px; }
.task-pct { font-size: 12px; color: var(--green-primary); white-space: nowrap; }

/* Alert rows */
.alert-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); }
.alert-row:last-child { border-bottom: none; }
.alert-info { flex: 1; }
.alert-text { font-size: 13px; color: var(--text-primary); }
.alert-time { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

/* Monitor rows */
.mon-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); }
.mon-row:last-child { border-bottom: none; }
.mon-label { font-size: 13px; color: var(--text-secondary); }
.mon-val { font-size: 16px; color: var(--text-primary); }
</style>
