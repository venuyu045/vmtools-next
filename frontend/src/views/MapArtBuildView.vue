<template>
  <div class="mapart-build-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <el-button size="small" @click="$router.push('/map-art-tasks')">← 地图画列表</el-button>
        <h2>地图画建造 · {{ task?.name || '未命名任务' }}</h2>
      </div>
      <div class="header-right">
        <el-tag :type="statusTagType">{{ statusLabel(task?.status) }}</el-tag>
        <span class="progress-text">{{ task?.placed_blocks ?? 0 }} / {{ task?.total_blocks ?? 0 }} 方块</span>
      </div>
    </div>

    <!-- 主体：预览画布 + 侧边面板 -->
    <div class="main-content">
      <!-- 2D 俯视预览画布 -->
      <div class="canvas-area">
        <div v-if="loadingBlocks" class="loading-canvas">正在加载方块数据…</div>
        <BuildMapCanvas
          v-else
          :task-id="taskId"
          :materials="materials"
          :init-data="blockData"
          :bot-positions="botMarkers"
          @ready="onCanvasReady"
        />

        <!-- 控制栏 -->
        <div class="control-bar">
          <el-button
            v-if="task?.status === 'draft' || task?.status === 'pending'"
            type="primary"
            @click="control('start')"
          >
            开始建造
          </el-button>
          <el-button
            v-if="task?.status === 'running'"
            @click="control('pause')"
          >
            暂停
          </el-button>
          <el-button
            v-if="task?.status === 'paused'"
            type="success"
            @click="control('resume')"
          >
            继续
          </el-button>
          <el-button
            v-if="task?.status === 'running' || task?.status === 'paused'"
            type="danger"
            @click="control('stop')"
          >
            停止
          </el-button>
        </div>

        <!-- 预览正下方：补货仓库配置（需求6/7） -->
        <SupplyConfigPanel :task-id="taskId" class="supply-panel" />
      </div>

      <!-- 右侧面板 -->
      <div class="side-panels">
        <!-- Bot 列表 -->
        <el-card class="panel" header="Bot 列表">
          <div class="bot-manage-bar">
            <el-select
              v-model="selectedAddBot"
              placeholder="选择要添加的 Bot"
              size="small"
              clearable
              :disabled="!canManageBots"
            >
              <el-option
                v-for="b in availableBots"
                :key="b.bot_id"
                :label="`${b.name || b.bot_id} [${b.status === 'online' ? '在线' : b.status}]`"
                :value="b.bot_id"
              />
            </el-select>
            <el-button size="small" type="primary" :disabled="!selectedAddBot || !canManageBots" @click="handleAddBot">
              添加
            </el-button>
            <el-tooltip content="仅运行中的任务可动态添加/移除 Bot" placement="top">
              <span class="manage-hint" v-if="!canManageBots">运行中才可管理</span>
            </el-tooltip>
          </div>
          <div v-if="!bots.length" class="empty">暂无分配的 Bot</div>
          <div v-for="bot in bots" :key="bot.bot_id" class="bot-row">
            <div class="bot-header">
              <span class="bot-dot" :style="{ background: botColor(bot.bot_id) }" />
              <strong>{{ bot.bot_name || bot.bot_id }}</strong>
              <el-tag size="small" :type="botStateType(bot.state)">{{ botStateLabel(bot.state) }}</el-tag>
              <el-button
                v-if="task?.status === 'draft' || task?.status === 'pending' || canManageBots"
                size="small"
                text
                type="danger"
                class="bot-remove"
                @click="handleRemoveBot(bot.bot_id)"
              >{{ canManageBots ? '移除' : '删除' }}</el-button>
            </div>
            <div class="bot-progress">
              <el-progress
                :percentage="bot.total ? Math.round(bot.placed / bot.total * 100) : 0"
                :stroke-width="6"
                :show-text="false"
              />
              <span class="bot-stats">{{ bot.placed }} / {{ bot.total }}</span>
            </div>
            <div class="bot-meta">
              <span>行 {{ bot.current_row >= 0 ? bot.current_row : '-' }}</span>
              <span>{{ (bot.rate ?? 0).toFixed(1) }} 块/分钟</span>
            </div>
          </div>
        </el-card>

        <!-- 材料需求 -->
        <el-card class="panel" header="材料需求">
          <div v-for="m in materials?.slice(0, 12)" :key="m.item_id" class="mat-row">
            <ItemIcon :item-id="m.item_id" :name="m.display_name" :size="24" class="mat-icon" />
            <span class="mat-name">{{ m.display_name }}</span>
            <span class="mat-count">{{ m.placed ?? 0 }} / {{ m.required }}</span>
          </div>
          <div v-if="!materials?.length" class="empty">暂无材料需求</div>
        </el-card>

        <!-- 统计 -->
        <el-card class="panel" header="统计">
          <div class="stat-row">
            <span>投影朝向</span>
            <span>{{ rotationLabel(task?.rotation) }}</span>
          </div>
          <div class="stat-row">
            <span>已耗时</span>
            <span>{{ formatTime(elapsed) }}</span>
          </div>
          <div class="stat-row">
            <span>预计剩余</span>
            <span>{{ formatTime(eta) }}</span>
          </div>
          <div class="stat-row">
            <span>平均速率</span>
            <span>{{ overallRate }} 块/分钟</span>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import BuildMapCanvas from '@/components/build/BuildMapCanvas.vue'
import SupplyConfigPanel from '@/components/build/SupplyConfigPanel.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { useSocketIO } from '@/composables/useSocketIO'
import { mapArtApi } from '@/api/mapArt'
import { botApi } from '@/api/bot'
import { errMsg } from '@/utils/error'
import { zhItemName } from '@/utils/itemZh'

const route = useRoute()
const taskId = computed(() => route.params.taskId as string)
const { on: sockOn, off: sockOff, emit: sockEmit } = useSocketIO()

// ── 方块数据缓存（2026-08-14 三期）：同任务再次进入不再重新"正在加载" ──
// 模块级 Map：组件卸载不丢，再次进入先用缓存秒开，后台静默刷新一次。
const blockCache = new Map<string, any>()

const task = ref<any>(null)
const bots = ref<any[]>([])
const materials = ref<any[]>([])
const blockData = ref<any>(null)
const loadingBlocks = ref(true)
const elapsed = ref(0)
const eta = ref(0)
const overallRate = ref('0')

// ── Bot 动态管理（需求4：添加/删除 bot，自动分配区域） ──
const selectedAddBot = ref('')
const availableBots = ref<any[]>([])
/** 仅运行中的任务可动态添加/移除 bot（后端校验，前端同步禁用） */
const canManageBots = computed(() => task.value?.status === 'running')

async function loadAvailableBots() {
  try {
    const { data } = await botApi.list()
    const all = Array.isArray(data) ? data : (data.bots || data.items || [])
    const assigned = new Set((bots.value || []).map((b: any) => b.bot_id))
    availableBots.value = all.filter((b: any) => !assigned.has(b.bot_id))
  } catch { /* 加载失败静默，添加按钮仍可点击尝试 */ }
}

async function handleAddBot() {
  if (!selectedAddBot.value || !canManageBots.value) return
  try {
    await mapArtApi.manageBot(taskId.value, 'add', selectedAddBot.value)
    ElMessage.success('Bot 已添加，自动分配待接管区域')
    selectedAddBot.value = ''
    fetchTask()
  } catch (e) {
    ElMessage.error(errMsg(e, '添加 Bot 失败'))
  }
}

async function handleRemoveBot(botId: string) {
  const running = canManageBots.value
  // 最后一个 bot 不允许删除（至少保留 1 个）
  if ((bots.value || []).length <= 1) {
    ElMessage.warning('至少保留 1 个 Bot')
    return
  }
  try {
    await ElMessageBox.confirm(
      running
        ? `确认移除 Bot「${botId}」？未完成区域将释放给后续添加的 Bot 接管`
        : `确认从任务中删除 Bot「${botId}」？剩余 Bot 的区域将自动重新划分`,
      '确认操作',
      { type: 'warning' },
    )
  } catch { return }
  try {
    await mapArtApi.manageBot(taskId.value, 'remove', botId)
    ElMessage.success(running ? 'Bot 已移除，未完成区域已释放' : 'Bot 已删除，剩余区域已重新划分')
    fetchTask()
  } catch (e) {
    ElMessage.error(errMsg(e, '操作失败'))
  }
}

// ── 状态中文映射（需求5：全页汉化） ──
const STATUS_LABELS: Record<string, string> = {
  draft: '草稿', pending: '待启动', running: '运行中',
  paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消',
}
const BOT_STATE_LABELS: Record<string, string> = {
  idle: '空闲', moving: '移动中', placing: '放置中', restocking: '补货中',
  waiting: '等待中', completed: '已完成', offline: '已离线', released: '已释放',
}
const ROTATION_LABELS: Record<number, string> = {
  0: '0°（北 / 原方向）', 1: '90°（东 / 顺时针）',
  2: '180°（南）', 3: '270°（西）',
}
function rotationLabel(r?: number): string {
  const n = ((r ?? 0) % 4 + 4) % 4
  return ROTATION_LABELS[n] || `${n}0°`
}

function statusLabel(s?: string): string { return (s && STATUS_LABELS[s]) || s || '未知' }
function botStateLabel(s?: string): string { return (s && BOT_STATE_LABELS[s]) || s || '未知' }

const statusTagType = computed(() => {
  const s = task.value?.status
  if (s === 'running') return 'success'
  if (s === 'completed') return ''
  if (s === 'failed') return 'danger'
  if (s === 'paused') return 'warning'
  return 'info'
})

function botStateType(state: string): string {
  if (state === 'placing' || state === 'completed') return 'success'
  if (state === 'offline' || state === 'failed') return 'danger'
  if (state === 'restocking' || state === 'moving') return 'warning'
  return 'info'
}

// ── bot 稳定颜色（与画布同算法：同一 bot 永远同色） ──
function stableColor(seed: string): string {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  const c = (h >>> 0) & 0xFFFFFF
  return `#${c.toString(16).padStart(6, '0')}`
}
function botColor(botId: string): string { return stableColor(botId) }

/** 传给画布的 bot 位置标记（含区域框数据） */
const botMarkers = computed(() =>
  (bots.value || []).map((b: any) => ({
    bot_id: b.bot_id,
    bot_name: b.bot_name || b.bot_id,
    state: b.state,
    position: b.position || null,
    region: b.region || null,
  }))
)

function formatTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}分 ${s}秒`
}

function onCanvasReady() {
  // 画布就绪
}

// ── 数据加载 ──

async function fetchTask() {
  try {
    const { data } = await mapArtApi.getTask(taskId.value)
    task.value = data
    // 材料名汉化（后端 display_name 可能为英文，前端映射兜底）
    materials.value = (data.materials || []).map((m: any) => ({
      ...m,
      display_name: m.display_name || zhItemName(m.item_id),
    }))
    bots.value = data.bots || []
    await loadAvailableBots()

    // 方块数据：有缓存先秒开（不再"正在加载"），后台静默刷新一次
    const cached = blockCache.get(taskId.value)
    if (cached) {
      blockData.value = cached
      loadingBlocks.value = false
    } else {
      loadingBlocks.value = true
    }
    try {
      const { data: blockResp } = await mapArtApi.getBlocks(taskId.value)
      const fresh = {
        task_id: blockResp.task_id,
        blocks: blockResp.blocks || [],
        bots: blockResp.bots || [],
        origin: blockResp.origin || { x: 0, y: 64, z: 0 },
        size: blockResp.size || { x: 32, z: 32 },
      }
      blockCache.set(taskId.value, fresh)
      blockData.value = fresh // 后台刷新：缓存/首次都更新为最新（含 placed 进度）
    } catch { /* 方块数据可能尚未生成；有缓存则保留缓存 */ }
    loadingBlocks.value = false
  } catch (e) {
    ElMessage.error(errMsg(e, '获取任务详情失败'))
  }
}

const ACTION_LABELS: Record<string, string> = {
  start: '开始', pause: '暂停', resume: '继续', stop: '停止',
}

async function control(action: string) {
  try {
    await mapArtApi.controlTask(taskId.value, action)
    ElMessage.success(`任务已${ACTION_LABELS[action] || action}`)
    fetchTask()
  } catch (e) {
    ElMessage.error(errMsg(e, `任务${ACTION_LABELS[action] || action}失败`))
  }
}

// ── Socket.IO 进度更新（组件级 handler 必须 onUnmounted 注销防累积） ──

onMounted(() => {
  fetchTask()
  sockEmit('build_map_join', { task_id: taskId.value })
  sockOn('build_progress', onBuildProgress)
  sockOn('build_bot_status', onBuildBotStatus)
})

onUnmounted(() => {
  sockOff('build_progress', onBuildProgress)
  sockOff('build_bot_status', onBuildBotStatus)
  sockEmit('build_map_leave', { task_id: taskId.value })
})

function onBuildProgress(data: any) {
  if (data.task_id !== taskId.value) return
  task.value = { ...task.value, status: data.status, placed_blocks: data.placed_blocks, total_blocks: data.total_blocks }
  elapsed.value = data.elapsed_sec || 0
  eta.value = data.eta_sec || 0
  overallRate.value = data.placed_blocks > 0 && data.elapsed_sec > 0
    ? (data.placed_blocks / (data.elapsed_sec / 60)).toFixed(1)
    : '0'
  // 注意：后端 _aggregate 的 materials 当前为 {}（未填充），空对象是 truthy——
  // 不加 length 检查会每 2s 把材料面板清空
  if (data.materials && Object.keys(data.materials).length > 0) {
    materials.value = Object.entries(data.materials).map(([k, v]: [string, any]) => ({
      item_id: k,
      display_name: zhItemName(k),
      placed: v.placed,
      required: v.required,
    }))
  }
}

function onBuildBotStatus(data: any) {
  if (data.task_id !== taskId.value) return
  bots.value = data.bots || []
}
</script>

<style scoped>
.mapart-build-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  gap: 12px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.header-left h2 {
  margin: 0;
  font-size: 20px;
  font-family: var(--font-display);
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.progress-text {
  color: var(--text-muted);
  font-size: 14px;
}
.main-content {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 300px;
  /* 2026-08-14 审查补录修复：行高 auto 时会被画布内容撑破（预览/补货窗口
     互相挤压）；改为 minmax(0,1fr) 固定为容器高度，两侧列内部滚动 */
  grid-template-rows: minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
}
.canvas-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow-y: auto;
}
.supply-panel { margin-top: 4px; }
.bot-manage-bar { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.bot-manage-bar .el-select { flex: 1; min-width: 0; }
.manage-hint { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.bot-remove { margin-left: auto; }
.loading-canvas {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  background: var(--bg-card);
  border-radius: 8px;
}
.control-bar {
  display: flex;
  gap: 8px;
  padding: 8px 0;
}
.side-panels {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  max-height: 100%;
}
.panel {
  flex-shrink: 0;
}
.bot-row {
  padding: 6px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.bot-row:last-child { border-bottom: none }
.bot-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bot-dot { width: 10px; height: 10px; border-radius: 50%; }
.bot-progress { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.bot-stats { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.bot-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); }
.mat-row {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 0; font-size: 12px;
}
.mat-icon { flex-shrink: 0; border-radius: 3px; }
.mat-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mat-count { color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.stat-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.empty { color: var(--text-muted); padding: 12px 0; text-align: center; }

/* 移动端：单列布局 */
@media (max-width: 900px) {
  .main-content { grid-template-columns: 1fr; }
  .side-panels { max-height: none; }
}
</style>