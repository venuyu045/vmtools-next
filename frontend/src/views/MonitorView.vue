<template>
  <div class="monitor-page">
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">> 系统监控</h2>
        <p class="mono page-subtitle">CPU / 内存 / 磁盘 / 网络 · 实时（Socket.IO 推送）</p>
      </div>
      <button class="pixel-btn outline" @click="refreshAll">刷新</button>
    </div>

    <!-- 概览统计 -->
    <div class="stat-row">
      <div class="pixel-card stat-item">
        <span class="stat-val" :style="{ color: '#d4a843' }">{{ latest?.cpu_percent != null ? latest.cpu_percent.toFixed(1) : '--' }}%</span>
        <span class="stat-lbl mono">CPU</span>
      </div>
      <div class="pixel-card stat-item">
        <span class="stat-val" :style="{ color: '#52c41a' }">{{ latest?.memory_percent != null ? latest.memory_percent.toFixed(1) : '--' }}%</span>
        <span class="stat-lbl mono">内存（{{ memText }}）</span>
      </div>
      <div class="pixel-card stat-item">
        <span class="stat-val" :style="{ color: '#1890ff' }">{{ latest?.disk_percent != null ? latest.disk_percent.toFixed(1) : '--' }}%</span>
        <span class="stat-lbl mono">磁盘（{{ diskText }}）</span>
      </div>
      <div class="pixel-card stat-item">
        <span class="stat-val" :style="{ color: '#ff7875' }">↑{{ netText.sent }} <span style="color:#69a7ff">↓{{ netText.recv }}</span></span>
        <span class="stat-lbl mono">网络速率</span>
      </div>
    </div>

    <div class="content-grid">
      <!-- 系统指标图 -->
      <div class="pixel-card chart-card">
        <div class="card-title">系统指标趋势</div>
        <MetricsChart :metrics="monitorStore.metrics" :height="300" />
      </div>

      <!-- 进程资源 -->
      <div class="pixel-card process-card">
        <div class="card-title">进程资源 <span class="card-count mono">{{ monitorStore.processes.length }}</span></div>
        <div v-if="monitorStore.processes.length === 0" class="empty mono">-- 暂无进程数据 --</div>
        <div v-else class="proc-list">
          <div v-for="(p, i) in monitorStore.processes" :key="i" class="proc-row">
            <span class="proc-role" :class="p.role">{{ roleLabel(p.role) }}</span>
            <span class="proc-name mono" :title="p.cmdline">{{ p.name }}</span>
            <span class="proc-pid mono">#{{ p.pid }}</span>
            <span class="proc-cpu mono" :style="{ color: p.cpu_percent > 60 ? '#f56c6c' : 'var(--green-primary)' }">{{ p.cpu_percent }}%</span>
            <span class="proc-mem mono">{{ p.mem_mb }}MB</span>
          </div>
        </div>
      </div>
    </div>

    <div class="content-grid">
      <!-- 告警事件时间线 -->
      <div class="pixel-card alert-card">
        <div class="card-title">告警事件 <span class="card-count mono">{{ monitorStore.alertEvents.length }}</span></div>
        <div v-if="monitorStore.alertEvents.length === 0" class="empty mono">-- 暂无告警事件（规则命中后在此显示） --</div>
        <div v-else class="alert-list">
          <div v-for="(ev, i) in monitorStore.alertEvents.slice(0, 20)" :key="i" class="alert-row">
            <span class="sev-tag" :class="ev.severity">{{ sevLabel(ev.severity) }}</span>
            <span class="alert-msg">{{ ev.message }}</span>
            <span class="alert-time mono">{{ fmtTime(ev.timestamp) }}</span>
          </div>
        </div>
      </div>

      <!-- 告警规则 -->
      <div class="pixel-card rule-card">
        <div class="card-title">告警规则 <span class="card-count mono">{{ monitorStore.alerts.length }}</span></div>
        <div v-if="monitorStore.alerts.length === 0" class="empty mono">-- 暂无告警规则 --</div>
        <div v-else class="rule-list">
          <div v-for="(r, i) in monitorStore.alerts" :key="i" class="rule-row">
            <span class="sev-tag" :class="r.severity">{{ sevLabel(r.severity) }}</span>
            <span class="rule-name">{{ r.name }}</span>
            <span class="rule-expr mono">{{ r.metric_name }} {{ r.operator }} {{ r.threshold }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useMonitorStore } from '@/stores/monitor'
import MetricsChart from '@/components/monitor/MetricsChart.vue'

const monitorStore = useMonitorStore()

const latest = computed(() => monitorStore.metrics[monitorStore.metrics.length - 1] || null)

function fmtBytes(n: number): string {
  if (!n || n <= 0) return '0'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(1) + units[i]
}

const memText = computed(() => latest.value ? `${fmtBytes(latest.value.memory_used)}/${fmtBytes(latest.value.memory_total)}` : '--')
const diskText = computed(() => latest.value ? `${fmtBytes(latest.value.disk_used)}/${fmtBytes(latest.value.disk_total)}` : '--')
const netText = computed(() => ({
  sent: latest.value?.net_sent_rate ? (latest.value.net_sent_rate / 1024).toFixed(1) + 'k' : '0',
  recv: latest.value?.net_recv_rate ? (latest.value.net_recv_rate / 1024).toFixed(1) + 'k' : '0',
}))

function sevLabel(s: string): string {
  const map: Record<string, string> = { warning: '警告', critical: '严重', error: '错误' }
  return map[s] || s
}

function roleLabel(r: string): string {
  const map: Record<string, string> = { mineflayer: 'MF', mcc: 'MCC', server: 'SVC' }
  return map[r] || r
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

async function refreshAll() {
  await Promise.all([
    monitorStore.fetchMetrics(60),
    monitorStore.fetchAlerts(),
    monitorStore.fetchAlertEvents(50),
    monitorStore.fetchProcesses(),
  ])
}

let fallbackTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  refreshAll()
  // 兜底轮询（socket 断连时仍能刷新）；socket 正常时数据由推送实时更新
  fallbackTimer = setInterval(() => {
    monitorStore.fetchMetrics(60)
    monitorStore.fetchProcesses()
  }, 30000)
})

onBeforeUnmount(() => {
  if (fallbackTimer) clearInterval(fallbackTimer)
})
</script>

<style scoped>
.monitor-page { display: flex; flex-direction: column; gap: 18px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.page-title { color: var(--green-primary); font-size: 16px; margin: 0 0 4px; }
.page-subtitle { color: var(--text-muted); font-size: 13px; margin: 0; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.stat-item { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; }
.stat-val { font-family: var(--font-mono); font-size: 20px; font-weight: 700; white-space: nowrap; }
.stat-lbl { color: var(--text-muted); font-size: 12px; }

.content-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; align-items: start; }
.card-title {
  font-family: var(--font-pixel);
  font-size: 13px;
  color: var(--green-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-count { color: var(--text-muted); font-size: 12px; }

/* 进程列表 */
.proc-list { display: flex; flex-direction: column; gap: 2px; max-height: 300px; overflow-y: auto; }
.proc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
}
.proc-row:last-child { border-bottom: none; }
.proc-role {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 6px;
  border: 1px solid var(--border-card);
  font-family: var(--font-mono);
}
.proc-role.mineflayer { color: #52c41a; border-color: rgba(82, 196, 26, 0.4); }
.proc-role.mcc { color: #1890ff; border-color: rgba(24, 144, 255, 0.4); }
.proc-role.server { color: #d4a843; border-color: rgba(212, 168, 67, 0.4); }
.proc-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
.proc-pid { color: var(--text-muted); flex-shrink: 0; }
.proc-cpu { flex-shrink: 0; width: 48px; text-align: right; }
.proc-mem { flex-shrink: 0; width: 64px; text-align: right; color: var(--text-secondary); }

/* 告警 */
.alert-list, .rule-list { display: flex; flex-direction: column; gap: 2px; max-height: 300px; overflow-y: auto; }
.alert-row, .rule-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
}
.alert-row:last-child, .rule-row:last-child { border-bottom: none; }
.sev-tag { flex-shrink: 0; font-size: 10px; padding: 1px 6px; border: 1px solid var(--border-card); font-family: var(--font-mono); }
.sev-tag.warning { color: #e6a23c; border-color: rgba(230, 162, 60, 0.4); }
.sev-tag.critical { color: #f56c6c; border-color: rgba(245, 108, 108, 0.5); background: rgba(245, 108, 108, 0.08); }
.sev-tag.error { color: #f56c6c; border-color: rgba(245, 108, 108, 0.4); }
.alert-msg { flex: 1; min-width: 0; color: var(--text-secondary); }
.alert-time { flex-shrink: 0; color: var(--text-muted); font-size: 11px; }
.rule-name { color: var(--text-primary); }
.rule-expr { color: var(--text-muted); font-size: 11px; }

.empty { color: var(--text-muted); text-align: center; padding: 24px 0; font-size: 13px; }

/* ============ RESPONSIVE ============ */
@media (max-width: 1024px) {
  .content-grid { grid-template-columns: 1fr; }
  .stat-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 480px) {
  .stat-row { grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-val { font-size: 16px; }
}
</style>