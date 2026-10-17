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
              v-if="bot.currentTask.type !== 'manual'"
              :percentage="taskPct(bot.currentTask)"
              :stroke-width="6"
              :status="bot.currentTask.status === 'completed' ? 'success' : undefined"
            />
            <div v-if="bot.currentTask.type !== 'manual'" class="task-meta mono">{{ taskProgressText(bot.currentTask) }}</div>
          </div>
          <div v-else class="task-box idle">
            <span class="idle-text">空闲 · 无执行任务</span>
          </div>

          <!-- 排队任务 -->
          <div v-if="bot.queuedTasks.length" class="queued-list">
            <div class="queued-title">排队中</div>
            <div v-for="q in bot.queuedTasks" :key="q.id" class="queued-item">
              <!-- 2026-10-15 审查修复：原三元表达式只区分「地图画/物流」，
                   仓库扫描（scan）排队任务被错误显示为「物流」。改用统一的
                   taskTypeLabel()，与上方当前任务卡片 / 任务列表口径一致。 -->
              <span class="task-type" :class="q.type">{{ taskTypeLabel(q.type) }}</span>
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
          <el-tab-pane label="仓库扫描" name="scan" />
        </el-tabs>
      </div>
      <el-table :data="pagedTasks" v-loading="loading" stripe empty-text="暂无任务" size="default">
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <span class="task-type" :class="row.type">{{ taskTypeLabel(row.type) }}</span>
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
        <el-table-column label="进度 / 任务信息" width="190">
          <template #default="{ row }">
            <el-progress
              :percentage="taskPct(row)"
              :stroke-width="6"
              :status="row.status === 'completed' ? 'success' : (row.status === 'failed' || row.status === 'cancelled' ? 'exception' : undefined)"
            />
            <div class="task-meta mono">{{ taskProgressText(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="用时" width="110">
          <template #default="{ row }">
            <span class="mono">{{ formatDuration(row.duration_seconds, row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="140">
          <template #default="{ row }">{{ fmtApiTime(row.created_at, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</template>
        </el-table-column>
        <!-- 任务中心为只读视图：无操作列（启动/暂停/恢复/停止/删除请前往对应任务详情页） -->
      </el-table>
      <div class="pager-row">
        <el-pagination
          v-if="filteredTasks.length > pageSize"
          layout="total, prev, pager, next"
          :total="filteredTasks.length"
          :page-size="pageSize"
          :current-page="page"
          @current-change="page = $event"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { tasksApi } from '@/api/tasks'
import { useSocketIO } from '@/composables/useSocketIO'
import { fmtApiTime } from '@/utils/time'

interface TaskRow {
  type: 'map_art' | 'logistics' | 'scan' | 'manual'
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
  /** 用时（秒，2026-08-13） */
  duration_seconds?: number | null
  /** 仓库扫描细节 */
  items_scanned?: number
  scanned_containers?: number
  total_containers?: number
  failed_containers?: number
  /** 物流细节 */
  current_state?: string | null
  loop_count?: number
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

const { on, off } = useSocketIO()

const loading = ref(false)
const tasks = ref<TaskRow[]>([])
const bots = ref<BotInfo[]>([])
const stats = ref({ running: 0, queued: 0, completed: 0, failed: 0, bot_total: 0, bot_online: 0, bot_idle: 0 })
const activeTab = ref('all')

/**
 * 拉取任务总览。
 *
 * 2026-10-15 审查修复：
 * 1) `silent`：socket 事件触发的刷新不再切换全屏 loading——原实现每次
 *    build_progress（地图画运行中约 2s 一次）都置 loading=true，导致表格
 *    反复闪烁「加载中」遮罩；仅首次加载与 30s 轮询显示 loading。
 * 2) 请求竞态保护（loadSeq）：socket 高频刷新与轮询可能并发，仅采纳最后
 *    一次发出的请求，避免旧响应覆盖新数据。
 */
let loadSeq = 0

async function fetchOverview(silent = false) {
  const seq = ++loadSeq
  if (!silent) loading.value = true
  try {
    const { data } = await tasksApi.getOverview()
    if (seq !== loadSeq) return // 已被更新的请求取代，丢弃本次响应
    tasks.value = data.tasks || []
    bots.value = data.bots || []
    stats.value = data.stats || stats.value
  } catch (e) {
    // 访客未登录时接口 401，静默（页面本身对访客只读，由 AppLayout 拦截交互）
    console.error('[TaskCenter] 加载任务数据失败:', e)
  } finally {
    if (!silent && seq === loadSeq) loading.value = false
  }
}

const filteredTasks = computed(() => {
  if (activeTab.value === 'all') return tasks.value
  return tasks.value.filter(t => t.type === activeTab.value)
})

// 分页（每页 10 条，2026-08-13）
const pageSize = 10
const page = ref(1)
const pagedTasks = computed(() => {
  const list = filteredTasks.value
  const start = (page.value - 1) * pageSize
  return list.slice(start, start + pageSize)
})
watch(activeTab, () => { page.value = 1 })

// 2026-10-15 审查修复：分页越界钳制。数据刷新（socket/轮询）后任务总数可能减少，
// 而 page 未重置 → 当前页落空（表格显示「暂无任务」但实际仍有数据）。
// 用 watch 监听过滤后列表长度，页码超出最大页时回退到最后一页。
watch(filteredTasks, () => {
  const maxPage = Math.max(1, Math.ceil(filteredTasks.value.length / pageSize))
  if (page.value > maxPage) page.value = maxPage
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
  return { manual: '手动', map_art: '地图画', logistics: '物流', scan: '仓库扫描' }[type] || type
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
  // 仓库扫描：扫描物品/容器/失败（2026-08-13 按任务类型显示具体信息）
  if (t.type === 'scan') {
    const parts: string[] = []
    if (t.items_scanned != null) parts.push(`物品 ${t.items_scanned}`)
    if (t.scanned_containers != null && t.total_containers != null) parts.push(`容器 ${t.scanned_containers}/${t.total_containers}`)
    if (t.failed_containers) parts.push(`失败 ${t.failed_containers}`)
    const pct = taskPct(t)
    return parts.length ? `${parts.join(' · ')}（${pct}%）` : `${pct}%`
  }
  // 物流：循环次数 + 当前状态
  if (t.type === 'logistics') {
    const bits: string[] = []
    if (t.loop_count != null && t.loop_count > 0) bits.push(`循环 ${t.loop_count} 次`)
    if (t.current_state && t.current_state !== 'IDLE') bits.push(t.current_state)
    const pct = taskPct(t)
    return bits.length ? `${pct}%${bits.map(b => ` · ${b}`).join('')}` : `${pct}%`
  }
  if (t.progress.percent != null) return `${taskPct(t)}%`
  return `${t.progress.placed || 0} / ${t.progress.total || 0} 方块`
}

/** 任务用时格式化（2026-08-13 替换原「详情」按钮） */
function formatDuration(sec: number | null | undefined, status: string): string {
  if (sec == null) return '—'
  const s = Math.max(0, Math.floor(sec))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const secs = s % 60
  if (d > 0) return `${d}天${h}时`
  if (h > 0) return `${h}时${m}分`
  if (m > 0) return `${m}分${secs}秒`
  return `${secs}秒`
}

function botStatusLabel(s: string): string {
  return { online: '在线', offline: '离线', connecting: '连接中', error: '错误', unknown: '未知' }[s] || s
}

/**
 * socket：build_progress（地图画进度）与 task_queue_update（队列变化）到达即刷新。
 * 2026-10-15：走 silent 模式——build_progress 在运行中约 2s 一次，若切 loading
 * 会让整个表格遮罩闪烁。守旧逻辑见 fetchOverview 注释。
 */
function onTaskEvent() {
  fetchOverview(true)
}

let pollTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  fetchOverview() // 首次加载：显示 loading
  on('build_progress', onTaskEvent)
  on('task_queue_update', onTaskEvent)
  // 轮询兜底同样 silent（避免每 30s 全表遮罩闪一下）
  pollTimer = setInterval(() => fetchOverview(true), 30000)
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
/* 悬停：全局 .stat-item:hover 已给橙色描边，这里只补一层柔和上浮阴影（transition 复用全局定义） */
.stat-item:hover { box-shadow: var(--shadow-md); }
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
/* 对齐修复：el-tabs 默认 15px 下边距会让标签条与左侧标题错位（section-header 为 center 对齐） */
.task-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
/* 分割线改用暖色 Token（EP 默认冷灰 #414243 在暖墨底上偏脏） */
.task-tabs :deep(.el-tabs__nav-wrap::after) { background-color: var(--border-subtle); }
.task-tabs :deep(.el-tabs__item) { font-size: 13px; color: var(--text-muted); transition: color var(--dur-fast) var(--ease-out); }
.task-tabs :deep(.el-tabs__item:hover) { color: var(--text-secondary); }
.task-tabs :deep(.el-tabs__item.is-active) { color: var(--accent); font-weight: 600; }
.task-tabs :deep(.el-tabs__active-bar) { background-color: var(--accent); height: 2px; }

.empty-text { color: var(--text-muted); text-align: center; padding: 24px; font-size: 14px; }
/* 深色下 --text-disabled(#6A675F) 在 #222119 上仅 2.9:1，提一级到 --text-muted */
.muted-text { color: var(--text-muted); font-size: 12px; }

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
.engine-badge.mineflayer { background: var(--accent-soft); color: var(--accent); }
.engine-badge.mcc { background: var(--info-bg); color: var(--info); }
.engine-badge.unknown { background: var(--bg-hover); color: var(--text-muted); }
.bot-name { font-size: 14px; font-weight: 600; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bot-status { font-size: 11px; padding: 1px 8px; border-radius: 999px; flex-shrink: 0; }
.bot-status.online { background: var(--success-bg); color: var(--success); }
.bot-status.offline, .bot-status.unknown { background: var(--bg-hover); color: var(--text-muted); }
.bot-status.connecting { background: var(--warning-bg); color: var(--warning); }
.bot-status.error { background: var(--danger-bg); color: var(--danger); }

.task-box { border-radius: var(--radius-md); padding: 10px 12px; }
.task-box.current { background: var(--bg-hover); border: 1px solid var(--border-subtle); }
.task-box.idle { background: transparent; border: 1px dashed var(--border-default); }
/* 空态文字原为 --text-disabled（深色下 2.9:1），提升到 --text-muted 保证可读 */
.idle-text { font-size: 12px; color: var(--text-muted); }
.task-box-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.task-name { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

.queued-list { display: flex; flex-direction: column; gap: 4px; }
.queued-title { font-size: 11px; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
.queued-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.queued-name { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 类型/状态徽标（10px 中文在深色下易糊，提到 11px） */
.task-type { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; flex-shrink: 0; }
/* 亮色默认压深一档（--accent 落在 accent-soft 上仅 2.56:1），深色用主题属性选择器覆盖回来。
   注：scoped 编译会把以 html 开头的选择器额外产出一条「去前缀」规则，导致覆盖失效，故用 [data-theme="dark"] */
.task-type.map_art { background: var(--accent-soft); color: #A94E2C; }
[data-theme="dark"] .task-type.map_art { color: var(--accent); }
.task-type.logistics { background: var(--info-bg); color: var(--info); }
/* 仓库扫描：橄榄绿（chart-3 系），亮色下压深一档保证 11px 文字可读 */
.task-type.scan { background: rgba(138, 154, 91, 0.18); color: #55622F; }
[data-theme="dark"] .task-type.scan { color: #9CAB6B; }
.task-type.manual { background: var(--bg-active); color: var(--text-secondary); }
.task-box.current.manual { border-color: var(--accent); }
.task-status { font-size: 11px; padding: 1px 8px; border-radius: 999px; flex-shrink: 0; }
.task-status.running { background: var(--accent-soft); color: var(--accent-hover); }
.task-status.pending, .task-status.draft { background: var(--warning-bg); color: var(--warning); }
.task-status.paused { background: var(--bg-active); color: var(--text-secondary); }
.task-status.completed { background: var(--success-bg); color: var(--success); }
.task-status.failed, .task-status.cancelled { background: var(--danger-bg); color: var(--danger); }

.bot-tags { display: flex; gap: 4px; flex-wrap: wrap; }
/* EP 暗色把 plain tag 的底色取成冷黑 #141414，落在暖墨卡片(#222119)上像“挖了个洞”，改用暖色 hover 底 */
.bot-tags :deep(.el-tag) {
  background: var(--bg-hover);
  border-color: var(--border-default);
  color: var(--text-secondary);
}

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

/* 分页（2026-08-13） */
.pager-row { display: flex; justify-content: flex-end; padding-top: 6px; }
/* 分页器未渲染（≤1 页）时不要留 6px 空白尾巴 */
.pager-row:empty { display: none; }
.mono { font-variant-numeric: tabular-nums; }
</style>