<template>
  <div class="mapart-build-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <el-button size="small" @click="$router.push('/map-art-tasks')">← 地图画列表</el-button>
        <h2>地图画建造 · {{ task?.name || '未命名任务' }}</h2>
      </div>
      <div class="header-right">
        <el-tag :type="statusTagType" :effect="isPaused ? 'dark' : 'light'">{{ statusLabel(displayStatus) }}</el-tag>
        <span class="progress-text">{{ task?.placed_blocks ?? 0 }} / {{ task?.total_blocks ?? 0 }} 方块</span>
      </div>
    </div>

    <!-- 控制栏（2026-08-14：独立行，位于页头与主体之间——与画布完全解耦，
         任何屏幕高度下都固定在页面顶部可见；task 未加载时不渲染空栏） -->
    <div class="control-bar" v-if="task">
      <el-button
        v-if="displayStatus === 'draft' || displayStatus === 'pending'"
        type="primary"
        @click="control('start')"
      >
        开始建造
      </el-button>
      <el-button
        v-else-if="canRestart"
        type="primary"
        @click="control('start')"
      >
        重新开始
      </el-button>
      <el-button
        v-if="displayStatus === 'running'"
        @click="control('pause')"
      >
        暂停
      </el-button>
      <el-button
        v-if="isPaused"
        type="success"
        @click="control('resume')"
      >
        继续
      </el-button>
      <el-button
        v-if="displayStatus === 'running' || isPaused"
        type="danger"
        @click="control('stop')"
      >
        停止
      </el-button>
      <span v-if="isPaused" class="paused-hint">已暂停 · Bot 保持待命，点「继续」从断点恢复</span>
    </div>

    <!-- 主体：左侧面板（预览已彻底移除 2026-08-18，用户确认不需要）+ 右侧面板 -->
    <div class="main-content">
      <!-- 左侧：补货仓库配置 + 实时日志 + Bot 背包 -->
      <div class="canvas-area">
        <SupplyConfigPanel :task-id="taskId" class="supply-panel" />

        <!-- 实时日志终端（2026-08-14：仓库补货列表下面，bot 活动实时反馈） -->
        <BuildLogPanel :task-id="taskId" />

        <!-- Bot 背包实时列表（2026-08-14：终端下面，正在工作的 bot 背包物品） -->
        <BotInventoryPanel :task-id="taskId" />
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
            <el-tooltip content="除已完成外均可添加/移除 Bot（失败/取消可先调整再重新开始）" placement="top">
              <span class="manage-hint" v-if="!canManageBots">已完成任务不可管理</span>
            </el-tooltip>
          </div>
          <div v-if="!botRows.length" class="empty">暂无分配的 Bot</div>
          <div v-for="bot in botRows" :key="bot.bot_id" class="bot-row">
            <div class="bot-header">
              <span class="bot-dot" :style="{ background: botColor(bot.bot_id) }" />
              <strong>{{ bot.name }}</strong>
              <el-tag size="small" :type="botStateType(bot.state)">{{ botStateLabel(bot.state) }}</el-tag>
              <el-button
                v-if="canManageBots"
                size="small"
                text
                type="danger"
                class="bot-remove"
                @click="handleRemoveBot(bot.bot_id)"
              >移除</el-button>
            </div>
            <div class="bot-progress">
              <el-progress
                :percentage="bot.pct"
                :stroke-width="6"
                :show-text="false"
              />
              <span class="bot-stats">{{ bot.placed }} / {{ bot.total }}</span>
            </div>
            <div class="bot-meta">
              <span v-if="task?.build_mode === 'column'">列 {{ bot.column ?? '-' }} · 排 {{ bot.squadIndex ?? 1 }}</span>
              <span v-else>行 {{ bot.currentRow !== null && bot.currentRow >= 0 ? bot.currentRow : '-' }}</span>
              <span class="bot-pos" :title="bot.position ? `世界坐标 (${fmtPos(bot.position)})` : '位置未知'">
                {{ bot.position ? fmtPos(bot.position) : '位置?' }}
              </span>
              <span>{{ bot.rate.toFixed(1) }} 块/分</span>
            </div>
          </div>
        </el-card>

        <!-- 列式编队（契约 §四新 WS 事件 build_squad_status，可选订阅：
             事件没来时 squadInfo 恒为 null，整块不渲染，不报错也不留空壳） -->
        <el-card v-if="squadInfo" class="panel" header="列式编队">
          <div class="stat-row">
            <span>当前排 · 方向</span>
            <span class="squad-headline">排 {{ squadInfo.squadIndex }} · 方向 {{ squadInfo.direction }}</span>
          </div>
          <div class="stat-row">
            <span>剩余列</span>
            <span>
              {{ squadInfo.remaining === null ? '-' : `${squadInfo.remaining} 列` }}
              <template v-if="squadInfo.totalColumns"> / 共 {{ squadInfo.totalColumns }} 列</template>
            </span>
          </div>
          <div v-if="!squadInfo.columns.length" class="empty">等待各列进度…</div>
          <div v-for="col in squadInfo.columns" :key="col.key" class="squad-col">
            <div class="squad-col-head">
              <span class="bot-dot" :style="{ background: botColor(col.botId || col.key) }" />
              <span class="squad-col-name">{{ col.botName }}</span>
              <el-tag v-if="col.done" size="small" type="success">已完成</el-tag>
              <el-tag v-else-if="col.state === 'offline'" size="small" type="danger">离线</el-tag>
              <span class="squad-col-x mono">世界 X {{ col.worldX ?? '-' }}</span>
            </div>
            <div class="squad-col-body">
              <el-progress :percentage="col.pct" :stroke-width="4" :show-text="false" />
              <span class="squad-col-stat">{{ col.placed }} / {{ col.total }}</span>
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
            <span>任务状态</span>
            <span :class="{ 'paused-text': isPaused }">{{ statusLabel(displayStatus) }}</span>
          </div>
          <div class="stat-row">
            <span>投影朝向</span>
            <span>{{ rotationLabel(task?.rotation) }}</span>
          </div>
          <div class="stat-row">
            <span>建造模式</span>
            <span>{{ task?.build_mode ? buildModeLabel(task?.build_mode) : '-' }}</span>
          </div>
          <div class="stat-row" v-if="task?.build_mode === 'column'">
            <span>当前排号</span>
            <span>
              第 {{ squadInfo?.squadIndex || squadIndex || task?.squad_index || 1 }} 排
              <template v-if="squadInfo"> · 方向 {{ squadInfo.direction }}</template>
            </span>
          </div>
          <div class="stat-row">
            <span>已耗时</span>
            <span>{{ formatTime(elapsed) }}</span>
          </div>
          <div class="stat-row">
            <span>预计剩余（整体）</span>
            <span>{{ formatTime(eta) }}</span>
          </div>
          <div class="stat-row">
            <span>净建造速率</span>
            <span>{{ netRate }} 块/分钟</span>
          </div>
          <div class="stat-row">
            <span>预计剩余（净速率）</span>
            <span>{{ formatTime(netEta) }}</span>
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
import SupplyConfigPanel from '@/components/build/SupplyConfigPanel.vue'
import BuildLogPanel from '@/components/build/BuildLogPanel.vue'
import BotInventoryPanel from '@/components/build/BotInventoryPanel.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { useSocketIO } from '@/composables/useSocketIO'
import {
  mapArtApi,
  botProgress,
  mergeBotList,
  squadDirectionLabel,
  buildModeLabel,
  type MapArtBuildAlert,
  type MapArtBuildProgress,
  type MapArtControlAction,
  type MapArtSquadColumn,
  type MapArtSquadStatus,
  type MapArtTaskBot,
  type MapArtTaskDetail,
  type MapArtTaskMaterial,
} from '@/api/mapArt'
import { botApi } from '@/api/bot'
import { errMsg } from '@/utils/error'
import { zhItemName } from '@/utils/itemZh'

const route = useRoute()
const taskId = computed(() => route.params.taskId as string)
const { on: sockOn, off: sockOff, emit: sockEmit, connectAsync: sockConnectAsync, connected: sockConnected } = useSocketIO()

const task = ref<MapArtTaskDetail | null>(null)
const bots = ref<MapArtTaskBot[]>([])
const materials = ref<MapArtTaskMaterial[]>([])
const elapsed = ref(0)
const eta = ref(0)
const overallRate = ref('0')
// 2026-08-19：净速率统计（多Bot列式模式）
const netRate = ref('0')
const netEta = ref(0)
const squadIndex = ref(0)

/**
 * 暂停态判定（修「暂停后仍显示运行中」+ 防「列式排尾等待被误显示成暂停」）。
 *
 * 两个来源：
 *   - `restStatus`：REST GET /tasks/{id}（DB 落库值，用户点暂停后由后端 commit，
 *     control() 之后必刷新）——**权威**
 *   - `liveStatus`：WS build_progress.status（实时，但列式引擎在「本列建完、等下一排
 *     分配」时会把 bot 置 waiting，后端 _compute_status 据此短暂返回 "paused"，
 *     这不是用户暂停）→ 需连续 2 次推送（≈4s）才采信，且随时可被 running 解除
 * 这样：用户暂停 → 立刻显示已暂停；排尾等待的抖动 → 不闪成暂停；恢复运行 → 立刻回来。
 */
const PAUSED_CONFIRM_PUSHES = 2
const restStatus = ref('')
const liveStatus = ref('')
const pausedStreak = ref(0)
/** 列式编队（可选事件 build_squad_status）：未收到时保持 null → 面板不渲染 */
const squadStatus = ref<MapArtSquadStatus | null>(null)

const displayStatus = computed(() => {
  const rest = restStatus.value
  const live = liveStatus.value
  // DB 终态（completed/failed/cancelled）优先：socket 的 paused 不能盖掉终态
  if (rest === 'completed' || rest === 'failed' || rest === 'cancelled') return rest
  // DB 已落库的 paused = 用户真的暂停了
  if (rest === 'paused') return 'paused'
  if (live === 'paused') {
    if (pausedStreak.value >= PAUSED_CONFIRM_PUSHES) return 'paused'
    // 抖动中的 paused：退回 REST 状态（通常是 running），不闪成暂停
    return rest || 'running'
  }
  return live || rest
})
const isPaused = computed(() => displayStatus.value === 'paused')

// ── Bot 动态管理（需求4：添加/删除 bot，自动分配区域） ──
const selectedAddBot = ref('')
const availableBots = ref<any[]>([])
/** 2026-08-19：除 completed 外的所有状态均可添加/移除 bot——
 * draft/pending 未开始、running/paused 运行中、failed/cancelled 可重新开始续建
 * （调整 bot 后再重启）；仅 completed 终态禁止（后端同样校验） */
const canManageBots = computed(() => {
  const s = displayStatus.value
  return s !== 'completed'
})
/** 2026-08-14：failed / cancelled / 未完成的 completed 任务可「重新开始」（断点续建，保留已放进度） */
const canRestart = computed(() => {
  const s = displayStatus.value
  if (s === 'failed' || s === 'cancelled') return true
  if (s === 'completed') {
    return (task.value?.placed_blocks ?? 0) < (task.value?.total_blocks ?? 0)
  }
  return false
})

/** Bot 列表展示行：进度字段统一由 botProgress() 归一化（A1），模板不再直读后端原始字段 */
interface BotRow {
  bot_id: string
  name: string
  state: string
  placed: number
  total: number
  rate: number
  pct: number
  column: number | null
  squadIndex: number | null
  currentRow: number | null
  position: MapArtTaskBot['position']
}
const botRows = computed<BotRow[]>(() => (bots.value || []).map((b) => {
  const p = botProgress(b)
  return {
    bot_id: b.bot_id,
    name: b.bot_name || b.name || b.bot_id,
    state: b.state || '',
    placed: p.placed,
    total: p.total,
    rate: p.rate,
    pct: p.pct,
    column: typeof b.column === 'number' ? b.column : null,
    squadIndex: typeof b.squad_index === 'number' ? b.squad_index : null,
    currentRow: typeof b.current_row === 'number' ? b.current_row : null,
    position: b.position ?? null,
  }
}))

/** 列式编队展示行（build_squad_status 归一化；列号 0-based，展示用世界 X） */
interface SquadColumnRow {
  key: string
  botId: string
  botName: string
  worldX: number | null
  done: boolean
  state: string
  placed: number
  total: number
  pct: number
}
const squadInfo = computed<{
  squadIndex: number
  direction: string
  remaining: number | null
  totalColumns: number | null
  columns: SquadColumnRow[]
} | null>(() => {
  const s = squadStatus.value
  if (!s) return null
  const nameOf = (botId: string): string => {
    const hit = bots.value.find(b => b.bot_id === botId)
    return hit?.bot_name || hit?.name || botId
  }
  const columns: SquadColumnRow[] = (s.columns || []).map((c: MapArtSquadColumn, i: number) => {
    const placed = Number(c.placed ?? 0) || 0
    const total = Number(c.total ?? 0) || 0
    return {
      key: `${c.bot_id || 'col'}-${c.column_x ?? i}`,
      botId: c.bot_id || '',
      botName: c.bot_id ? nameOf(c.bot_id) : `第 ${i + 1} 列`,
      worldX: typeof c.world_x === 'number' ? c.world_x : null,
      done: !!c.done,
      state: c.state || '',
      placed,
      total,
      pct: total > 0
        ? Math.min(100, Math.max(0, Math.round((placed / total) * 100)))
        : (c.done ? 100 : 0),
    }
  })
  return {
    squadIndex: Number(s.squad_index ?? squadIndex.value ?? 1) || 1,
    direction: squadDirectionLabel(s.direction),
    remaining: typeof s.remaining_columns === 'number' ? s.remaining_columns : null,
    totalColumns: typeof s.total_columns === 'number' ? s.total_columns : null,
    columns,
  }
})

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
    const { data } = await mapArtApi.manageBot(taskId.value, 'add', selectedAddBot.value)
    const running = displayStatus.value === 'running' || isPaused.value
    ElMessage.success(
      running
        ? 'Bot 已添加，自动分配待接管区域'
        : (data?.message || 'Bot 已加入任务，启动时统一分配列/区域'),
    )
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
        ? `确认移除 Bot「${botId}」？运行中未完成区域将释放给后续添加的 Bot 接管`
        : `确认从任务中移除 Bot「${botId}」？剩余 Bot 的区域/列将自动重新划分`,
      '确认操作',
      { type: 'warning' },
    )
  } catch { return }
  try {
    await mapArtApi.manageBot(taskId.value, 'remove', botId)
    ElMessage.success(running ? 'Bot 已移除，未完成区域已释放' : 'Bot 已移除，剩余区域已重新划分')
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
  waiting: '等待中', paused: '已暂停', completed: '已完成', offline: '已离线', released: '已释放',
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
  const s = displayStatus.value
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

function formatTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}分 ${s}秒`
}

/** 2026-08-19：bot 世界坐标位置显示（build_bot_status 实时推送） */
function fmtPos(pos: MapArtTaskBot['position']): string {
  if (!pos) return '-'
  const x = typeof pos.x === 'number' ? Math.round(pos.x) : pos.x
  const y = typeof pos.y === 'number' ? Math.round(pos.y) : pos.y
  const z = typeof pos.z === 'number' ? Math.round(pos.z) : pos.z
  return `${x},${y},${z}`
}

/** 记录 WS 推送的实时状态，并维护 paused 连续推送计数（见 displayStatus 注释） */
function trackLiveStatus(status?: string) {
  if (!status) return
  liveStatus.value = status
  pausedStreak.value = status === 'paused' ? pausedStreak.value + 1 : 0
}

/**
 * Bot 列表合并（A1 补充 + 保留 per-bot state）。
 *
 * build_bot_status 不带 region，build_progress.bots 不带 position/column，
 * 直接整体替换会来回丢字段（位置/列号一闪一闪）→ 按 bot_id 合并，见 mergeBotList()。
 * 空数组默认忽略（防瞬时抖动把列表刷空），REST 全量刷新时传 allowEmpty。
 */
function mergeBots(incoming?: MapArtTaskBot[] | null, allowEmpty = false) {
  bots.value = mergeBotList(bots.value, incoming, allowEmpty)
}

// ── 数据加载 ──

async function fetchTask() {
  try {
    const { data } = await mapArtApi.getTask(taskId.value)
    // 2026-08-14 修复：get_task 返回 progress 嵌套对象，原代码直接读顶层
    // task.placed_blocks/total_blocks → undefined → 页头 0/0、canRestart 0<0=false
    // → 控制栏按钮永远不渲染（截图实测根因）。统一展平到顶层供模板使用。
    task.value = {
      ...data,
      placed_blocks: data.progress?.placed_blocks ?? data.placed_blocks ?? 0,
      total_blocks: data.progress?.total_blocks ?? data.total_blocks ?? 0,
    }
    // REST 是暂停态的权威来源（DB 落库值；control 之后必刷新）
    restStatus.value = data.status || ''
    pausedStreak.value = 0
    // 材料名汉化（后端 display_name 可能为英文，前端映射兜底）
    materials.value = (data.materials || []).map((m) => ({
      ...m,
      display_name: m.display_name || zhItemName(m.item_id),
    }))
    // REST 是 Bot 成员关系的权威来源（可整体为空），但保留 socket 带来的实时字段
    mergeBots(data.bots, true)
    await loadAvailableBots()
  } catch (e) {
    ElMessage.error(errMsg(e, '获取任务详情失败'))
  }
}

const ACTION_LABELS: Record<string, string> = {
  start: '开始', pause: '暂停', resume: '继续', stop: '停止',
}

async function control(action: MapArtControlAction) {
  try {
    const { data } = await mapArtApi.controlTask(taskId.value, action)
    // 用户主动操作立即生效：用响应里的 status 先翻转按钮态，再 fetchTask 校准
    const respStatus = (data as { status?: string } | undefined)?.status
    if (respStatus) restStatus.value = respStatus
    liveStatus.value = ''
    pausedStreak.value = 0
    ElMessage.success(`任务已${ACTION_LABELS[action] || action}`)
    fetchTask()
  } catch (e) {
    ElMessage.error(errMsg(e, `任务${ACTION_LABELS[action] || action}失败`))
  }
}

// ── Socket.IO 进度更新（组件级 handler 必须 onUnmounted 注销防累积） ──

/**
 * A4：深链进入时 socket 可能还没建连 —— 原实现先 `sockEmit('build_map_join')`
 * 再注册监听，socket 为 null 时 emit 被静默丢弃 → 房间没进 → 历史日志回放和
 * 进度推送全丢（页面看着正常但永远不刷新）。
 *
 * 现在的口径：
 *   1) onMounted 先 await connectAsync()，连上再 join；连不上给可见提示
 *   2) 'connect' 事件里也 join 一次 —— 覆盖「首次建连」与「断线后自动重连」
 *      （room 成员关系不跨连接保留，重连必须重新进房）
 */
function joinBuildRoom() {
  sockEmit('build_map_join', { task_id: taskId.value })
}

function onSocketConnected() {
  joinBuildRoom()
}

async function ensureJoined() {
  const alreadyConnected = sockConnected()
  const ok = await sockConnectAsync(8000)
  if (!ok) {
    ElMessage.warning('实时通道未连接：进度/日志可能不刷新（后台自动重连中，可稍后刷新页面）')
    return
  }
  // 早已连接时 connect 事件不会再来，这里补一次 join；否则交给 onSocketConnected
  if (alreadyConnected) joinBuildRoom()
}

onMounted(() => {
  // useSocketIO 的 on() 已支持「未建连时先登记、建连时补挂」，故先注册再建连不会丢事件
  sockOn('connect', onSocketConnected)
  sockOn('build_progress', onBuildProgress)
  sockOn('build_bot_status', onBuildBotStatus)
  // 契约 §四新增事件：可选订阅，后端未实现/老任务永不触发 → 静默
  sockOn('build_squad_status', onBuildSquadStatus)
  // A3：非 admin 订阅会被后端回 build_alert（原来静默 return，前端毫无反馈）
  sockOn('build_alert', onBuildAlert)
  void ensureJoined()
  fetchTask()
})

onUnmounted(() => {
  sockOff('connect', onSocketConnected)
  sockOff('build_progress', onBuildProgress)
  sockOff('build_bot_status', onBuildBotStatus)
  sockOff('build_squad_status', onBuildSquadStatus)
  sockOff('build_alert', onBuildAlert)
  sockEmit('build_map_leave', { task_id: taskId.value })
})

function onBuildProgress(data: MapArtBuildProgress) {
  if (!data || data.task_id !== taskId.value) return
  // status 可能缺省（failed / completed 的单发事件只有 status/error）→ 不覆盖已有值
  const patch: Partial<MapArtTaskDetail> = {}
  if (data.status) patch.status = data.status
  if (typeof data.placed_blocks === 'number') patch.placed_blocks = data.placed_blocks
  if (typeof data.total_blocks === 'number') patch.total_blocks = data.total_blocks
  if (data.error_message) patch.error_message = data.error_message
  task.value = { ...(task.value || { task_id: taskId.value }), ...patch }
  trackLiveStatus(data.status)

  elapsed.value = data.elapsed_sec || 0
  eta.value = data.eta_sec || 0
  overallRate.value = (data.placed_blocks ?? 0) > 0 && (data.elapsed_sec ?? 0) > 0
    ? ((data.placed_blocks as number) / ((data.elapsed_sec as number) / 60)).toFixed(1)
    : '0'
  // 2026-08-19：净速率 / 排号（多Bot列式模式）
  netRate.value = (data.net_rate ?? 0) > 0 ? String(data.net_rate) : '0'
  netEta.value = data.net_eta || 0
  if (typeof data.squad_index === 'number' && data.squad_index > 0) {
    squadIndex.value = data.squad_index
  }
  // A1 补充：build_progress.bots 里本来就有 placed/total/rate（旧代码直接丢弃了 bots）
  // → 合并进 Bot 列表，进度不再等 2s 一次的 build_bot_status
  mergeBots(data.bots)
  // 注意：后端 _aggregate 的 materials 当前为 {}（未填充），空对象是 truthy——
  // 不加 length 检查会每 2s 把材料面板清空
  if (data.materials && Object.keys(data.materials).length > 0) {
    materials.value = Object.entries(data.materials).map(([k, v]) => ({
      item_id: k,
      display_name: zhItemName(k),
      placed: v?.placed,
      required: v?.required,
    }))
  }
}

function onBuildBotStatus(data: { task_id?: string; bots?: MapArtTaskBot[] }) {
  if (!data || data.task_id !== taskId.value) return
  // 合并而非替换：保留 per-bot state / region / position，空 payload 不清空列表
  mergeBots(data.bots)
}

/** 契约 §四新事件（可选）：列式编队状态 —— 排号/方向/各列进度/剩余列 */
function onBuildSquadStatus(data: MapArtSquadStatus) {
  if (!data || data.task_id !== taskId.value) return
  squadStatus.value = data
}

/** A3/A4：订阅或控制失败时后端回 build_alert，必须给用户可见提示 */
function onBuildAlert(data: MapArtBuildAlert) {
  const msg = data?.message || '建造实时通道异常'
  if (data?.type === 'error') ElMessage.error(msg)
  else ElMessage.warning(msg)
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
.control-bar {
  display: flex;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}
/* 暂停态可见提示（控制栏右侧） */
.paused-hint {
  margin-left: auto;
  align-self: center;
  font-size: 12px;
  color: var(--warning);
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
.bot-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.bot-progress { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.bot-stats { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.bot-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); }
/* 列式编队面板 */
.squad-headline { color: var(--accent); }
.squad-col { padding: 6px 0; border-bottom: 1px solid var(--border-subtle); }
.squad-col:last-child { border-bottom: none; }
.squad-col-head { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.squad-col-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.squad-col-x { color: var(--text-muted); font-size: 11px; }
.squad-col-body { display: flex; align-items: center; gap: 8px; margin-top: 3px; }
.squad-col-stat { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.mat-row {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 0; font-size: 12px;
}
.mat-icon { flex-shrink: 0; border-radius: 3px; }
.mat-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mat-count { color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.stat-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.paused-text { color: var(--warning); }
.empty { color: var(--text-muted); padding: 12px 0; text-align: center; }

/* 移动端：单列布局 */
@media (max-width: 900px) {
  .main-content { grid-template-columns: 1fr; }
  .side-panels { max-height: none; }
}
</style>
