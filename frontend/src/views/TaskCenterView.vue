<template>
  <div class="task-center">
    <!-- 概览统计卡 -->
    <div class="stats-row">
      <div class="stat-item">
        <span class="stat-value" style="color: var(--chart-1)">{{ stats.running }}</span>
        <div>
          <div class="stat-label">运行中</div>
          <div class="stat-sub">任务</div>
        </div>
      </div>
      <div class="stat-item">
        <span class="stat-value" style="color: var(--chart-2)">{{ stats.queued }}</span>
        <div>
          <div class="stat-label">排队中</div>
          <div class="stat-sub">等待调度</div>
        </div>
      </div>
      <div class="stat-item">
        <span class="stat-value" style="color: var(--chart-3)">{{ stats.completed }}</span>
        <div>
          <div class="stat-label">已完成</div>
          <div class="stat-sub">历史记录</div>
        </div>
      </div>
      <div class="stat-item">
        <span class="stat-value" style="color: var(--chart-5)">{{ stats.bot_idle }}<span class="stat-slash">/{{ stats.bot_total }}</span></span>
        <div>
          <div class="stat-label">空闲 Bot</div>
          <div class="stat-sub">在线 {{ stats.bot_online }}</div>
        </div>
      </div>
    </div>

    <!-- Bot 执行视角（核心） -->
    <div class="section">
      <div class="section-header">
        <h3 class="section-title">Bot 执行视角</h3>
        <span class="section-sub">每个 Bot 正在执行 / 排队中的任务</span>
      </div>
      <div v-if="bots.length === 0" class="empty-text">-- 暂无 Bot --</div>
      <div v-else class="bot-grid">
        <div v-for="bot in botCards" :key="bot.bot_id" class="bot-card">
          <div class="bot-head">
            <span class="engine-badge mineflayer">MF</span>
            <span class="bot-name">{{ bot.name }}</span>
            <span class="bot-status" :class="bot.status">{{ botStatusLabel(bot.status) }}</span>
          </div>

          <!-- 当前任务（手动标记「工作中」优先展示，2026-08-13 任务管理） -->
          <div v-if="bot.currentTask" class="task-box current" :class="{ manual: bot.currentTask.type === 'manual' }">
            <div class="task-box-head">
              <span class="task-type" :class="bot.currentTask.type">{{ taskTypeLabel(bot.currentTask.type) }}</span>
              <span class="task-name" :title="bot.currentTask.name">{{ bot.currentTask.name }}</span>
              <span class="task-status" :class="bot.currentTask.status">{{ bot.currentTask.status_label }}</span>
            </div>
            <el-progress
              :percentage="taskPct(bot.currentTask)"
              :stroke-width="6"
              :status="bot.currentTask.status === 'completed' ? 'success' : undefined"
            />
            <div class="task-meta mono">{{ taskProgressText(bot.currentTask) }}</div>
          </div>
          <div v-else class="task-box idle">
            <span class="idle-text">空闲 · 无执行任务</span>
          </div>

          <!-- 排队任务 -->
          <div v-if="bot.queuedTasks.length" class="queued-list">
            <div class="queued-title">排队中</div>
            <div v-for="q in bot.queuedTasks" :key="q.id" class="queued-item">
              <span class="task-type" :class="q.type">{{ q.type === 'map_art' ? '地图画' : '物流' }}</span>
              <span class="queued-name" :title="q.name">{{ q.name }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 统一任务列表 -->
    <div class="section">
      <div class="section-header">
        <h3 class="section-title">任务列表</h3>
        <el-tabs v-model="activeTab" class="task-tabs">
          <el-tab-pane label="全部" name="all" />
          <el-tab-pane label="地图画建造" name="map_art" />
          <el-tab-pane label="物流任务" name="logistics" />
        </el-tabs>
      </div>
      <el-table :data="filteredTasks" v-loading="loading" stripe empty-text="暂无任务" size="default">
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <span class="task-type" :class="row.type">{{ row.type === 'map_art' ? '地图画' : '物流' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="任务名" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="task-status" :class="row.status">{{ row.status_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="指派 Bot" min-width="130">
          <template #default="{ row }">
            <span v-if="row.bots.length" class="bot-tags">
              <el-tag v-for="b in row.bots" :key="b.bot_id" size="small" effect="plain">{{ b.bot_name }}</el-tag>
            </span>
            <span v-else class="muted-text">—</span>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="taskPct(row)"
              :stroke-width="6"
              :status="row.status === 'completed' ? 'success' : (row.status === 'failed' || row.status === 'cancelled' ? 'exception' : undefined)"
            />
            <div class="task-meta mono">{{ taskProgressText(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ fmtApiTime(row.created_at, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <template v-if="authStore.isAdmin">
              <el-button v-if="row.type === 'map_art' && ['draft', 'pending'].includes(row.status)" size="small" type="primary" plain @click="controlTask(row, 'start')">启动</el-button>
              <el-button v-if="row.status === 'running'" size="small" @click="controlTask(row, 'pause')">暂停</el-button>
              <el-button v-if="row.status === 'paused'" size="small" @click="controlTask(row, 'resume')">恢复</el-button>
              <el-button v-if="['running', 'paused', 'pending', 'draft'].includes(row.status)" size="small" type="warning" plain @click="controlTask(row, 'stop')">停止</el-button>
              <el-button v-if="row.type === 'map_art' && ['draft', 'cancelled', 'completed'].includes(row.status)" size="small" type="danger" plain @click="deleteTask(row)">删除</el-button>
            </template>
            <el-button size="small" @click="goDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tasksApi } from '@/api/tasks'
import { mapArtApi } from '@/api/mapArt'
import { logisticsApi } from '@/api/logistics'
import { useAuthStore } from '@/stores/auth'
import { useSocketIO } from '@/composables/useSocketIO'
import { fmtApiTime } from '@/utils/time'

interface TaskRow {
  type: 'map_art' | 'logistics' | 'manual'
  id: string
  name: string
  status: string
  status_label: string
  progress: { placed?: number; total?: number; percent?: number }
  bots: { bot_id: string; bot_name: string; state?: string }[]
  engine: string
  detail_url?: string
  created_at?: string
  error_message?: string | null
}

interface BotInfo {
  bot_id: string
  name: string
  status: string
  engine: string
  busy: boolean
  /** 手动标记「工作中」（2026-08-13 任务管理） */
  manual?: { working: boolean; name: string } | null
}

const router = useRouter()
const authStore = useAuthStore()
const { on, off } = useSocketIO()

const loading = ref(false)
const tasks = ref<TaskRow[]>([])
const bots = ref<BotInfo[]>([])
const stats = ref({ running: 0, queued: 0, completed: 0, failed: 0, bot_total: 0, bot_online: 0, bot_idle: 0 })
const activeTab = ref('all')

async function fetchOverview() {
  loading.value = true
  try {
    const { data } = await tasksApi.getOverview()
    tasks.value = data.tasks || []
    bots.value = data.bots || []
    stats.value = data.stats || stats.value
  } catch (e) {
    // 访客未登录时接口 401，静默（页面本身对访客只读，由 AppLayout 拦截交互）
    console.error('[TaskCenter] 加载任务数据失败:', e)
  } finally {
    loading.value = false
  }
}

const filteredTasks = computed(() => {
  if (activeTab.value === 'all') return tasks.value
  return tasks.value.filter(t => t.type === activeTab.value)
})

/** Bot → 当前任务 + 排队任务映射（手动标记「工作中」优先展示，2026-08-13） */
const botCards = computed(() => {
  return bots.value.map(bot => {
    const current = tasks.value.find(t => t.status === 'running' && t.bots.some(b => b.bot_id === bot.bot_id))
    const queued = tasks.value.filter(t => t.status === 'pending' && t.bots.some(b => b.bot_id === bot.bot_id))
    const manualTask: TaskRow | null = bot.manual
      ? { type: 'manual', id: `manual-${bot.bot_id}`, name: bot.manual.name, status: 'running', status_label: '工作中', progress: {}, bots: [], engine: 'mineflayer' }
      : null
    return { ...bot, currentTask: manualTask || current || null, queuedTasks: queued }
  })
})

function taskTypeLabel(type: string): string {
  return { manual: '手动', map_art: '地图画', logistics: '物流' }[type] || type
}

function taskPct(t: TaskRow): number {
  if (t.progress.percent != null) {
    return Math.min(100, Math.max(0, t.progress.percent))
  }
  const total = t.progress.total || 0
  if (!total) return 0
  return Math.min(100, Math.round(((t.progress.placed || 0) / total) * 100))
}

function taskProgressText(t: TaskRow): string {
  if (t.progress.percent != null) return `${taskPct(t)}%`
  return `${t.progress.placed || 0} / ${t.progress.total || 0} 方块`
}

function botStatusLabel(s: string): string {
  return { online: '在线', offline: '离线', connecting: '连接中', error: '错误', unknown: '未知' }[s] || s
}

async function controlTask(row: TaskRow, action: string) {
  try {
    if (row.type === 'map_art') {
      const { data } = await mapArtApi.controlTask(row.id, action)
      ElMessage.success(data?.message || `任务已${action}`)
    } else {
      if (action === 'stop') await logisticsApi.stopTask(row.id)
      else if (action === 'pause') await logisticsApi.pauseTask(row.id)
      else if (action === 'resume') await logisticsApi.resumeTask(row.id)
      else { ElMessage.info('物流任务由模板页启动'); return }
      ElMessage.success(`任务已${action}`)
    }
    fetchOverview()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || `操作失败: ${action}`)
  }
}

async function deleteTask(row: TaskRow) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.name}」？`, '确认', { type: 'warning' })
    await mapArtApi.deleteTask(row.id)
    ElMessage.success('已删除')
    fetchOverview()
  } catch { /* 取消 */ }
}

function goDetail(row: TaskRow) {
  if (row.type === 'map_art') {
    router.push(`/map-art/${row.id}`)
  } else {
    router.push('/logistics/runs')
  }
}

/** socket：build_progress（地图画进度）与 task_queue_update（队列变化）到达即刷新 */
function onTaskEvent() {
  fetchOverview()
}

let pollTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  fetchOverview()
  on('build_progress', onTaskEvent)
  on('task_queue_update', onTaskEvent)
  pollTimer = setInterval(fetchOverview, 30000)
})

onBeforeUnmount(() => {
  off('build_progress', onTaskEvent)
  off('task_queue_update', onTaskEvent)
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.task-center { display: flex; flex-direction: column; gap: 24px; }

.stats-row { display: flex; gap: 16px; flex-wrap: wrap; }
.stat-item {
  flex: 1 1 150px;
  min-width: 170px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.stat-value {
  font-size: 28px;
  font-family: var(--font-display);
  font-weight: 400;
  letter-spacing: -0.8px;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
  white-space: nowrap;
}
.stat-slash { font-size: 14px; color: var(--text-muted); }
.stat-label { font-size: 14px; color: var(--text-primary); font-weight: 600; }
.stat-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

.section { display: flex; flex-direction: column; gap: 12px; }
.section-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.section-title { font-family: var(--font-display); font-size: 20px; font-weight: 400; letter-spacing: -0.5px; color: var(--text-primary); margin: 0; }
.section-sub { font-size: 12px; color: var(--text-muted); }
.task-tabs { margin: 0; }

.empty-text { color: var(--text-muted); text-align: center; padding: 24px; font-size: 14px; }
.muted-text { color: var(--text-disabled); font-size: 12px; }

/* ---- Bot 卡片 ---- */
.bot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.bot-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: var(--shadow-sm);
}
.bot-head { display: flex; align-items: center; gap: 8px; }
.engine-badge {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 999px;
  flex-shrink: 0;
}
.engine-badge.mineflayer { background: rgba(217, 119, 87, 0.15); color: var(--accent); }
.engine-badge.mcc { background: rgba(108, 122, 140, 0.15); color: #6c7a8c; }
.engine-badge.unknown { background: rgba(144, 147, 153, 0.15); color: #909399; }
.bot-name { font-size: 14px; font-weight: 600; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bot-status { font-size: 11px; padding: 1px 8px; border-radius: 999px; flex-shrink: 0; }
.bot-status.online { background: rgba(103, 194, 58, 0.15); color: #67c23a; }
.bot-status.offline, .bot-status.unknown { background: rgba(144, 147, 153, 0.15); color: #909399; }
.bot-status.connecting { background: rgba(230, 162, 60, 0.15); color: #e6a23c; }
.bot-status.error { background: rgba(245, 108, 108, 0.15); color: #f56c6c; }

.task-box { border-radius: var(--radius-md); padding: 10px 12px; }
.task-box.current { background: var(--bg-hover); border: 1px solid var(--border-subtle); }
.task-box.idle { background: transparent; border: 1px dashed var(--border-default); }
.idle-text { font-size: 12px; color: var(--text-disabled); }
.task-box-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.task-name { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

.queued-list { display: flex; flex-direction: column; gap: 4px; }
.queued-title { font-size: 11px; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
.queued-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.queued-name { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 类型/状态徽标 */
.task-type { font-size: 10px; font-weight: 700; padding: 1px 8px; border-radius: 999px; flex-shrink: 0; }
.task-type.map_art { background: rgba(217, 119, 87, 0.15); color: var(--accent); }
.task-type.logistics { background: rgba(108, 122, 140, 0.15); color: #6c7a8c; }
.task-type.manual { background: rgba(217, 119, 87, 0.2); color: var(--accent); }
.task-box.current.manual { border-color: var(--accent); }
.task-status { font-size: 11px; padding: 1px 8px; border-radius: 999px; flex-shrink: 0; }
.task-status.running { background: rgba(64, 158, 255, 0.15); color: #409eff; }
.task-status.pending, .task-status.draft { background: rgba(230, 162, 60, 0.15); color: #e6a23c; }
.task-status.paused { background: rgba(144, 147, 153, 0.2); color: #909399; }
.task-status.completed { background: rgba(103, 194, 58, 0.15); color: #67c23a; }
.task-status.failed, .task-status.cancelled { background: rgba(245, 108, 108, 0.15); color: #f56c6c; }

.bot-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.bot-tags :deep(.el-tag) { border-color: var(--border-default); color: var(--text-secondary); }

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .task-center { gap: 16px; }
  .stats-row { gap: 10px; }
  .stats-row .stat-item { flex: 1 1 calc(50% - 10px); min-width: 140px; padding: 14px; }
  .stat-value { font-size: 22px; }
  .bot-grid { grid-template-columns: 1fr; }
  .section-header { flex-direction: column; align-items: flex-start; }
  .task-tabs { width: 100%; }
}
</style>