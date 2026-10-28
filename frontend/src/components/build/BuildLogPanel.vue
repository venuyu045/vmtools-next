<template>
  <el-card class="panel build-log-panel" header="实时日志终端">
    <div class="log-toolbar">
      <el-switch v-model="autoScroll" size="small" />
      <span class="log-toolbar-label">自动滚动</span>
      <el-radio-group v-model="detailMode" size="small" class="log-mode">
        <el-radio-button :value="false">简略</el-radio-button>
        <el-radio-button :value="true">详细</el-radio-button>
      </el-radio-group>
      <span class="log-toolbar-label">详细模式显示所有操作（含 debug）</span>
      <el-button size="small" text type="danger" class="log-clear" @click="clearLog">清空</el-button>
    </div>
    <!-- 2026-08-19：per-bot 独立日志窗口 —— 全部（全局事件流）/ 各Bot 独立终端 -->
    <div class="log-bot-filter">
      <el-radio-group v-model="selectedBot" size="small" @change="scrollToBottom">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button
          v-for="bid in botIds"
          :key="bid"
          :value="bid"
        >{{ botName(bid) }}</el-radio-button>
      </el-radio-group>
    </div>
    <div ref="logBody" class="log-body">
      <div v-for="(entry, i) in filteredLogs" :key="i" class="log-line" :class="`log-${entry.level || 'info'}`">
        <span class="log-time mono">{{ formatTime(entry.ts) }}</span>
        <span class="log-bot">{{ entry.bot_name || entry.bot_id }}</span>
        <span class="log-msg">{{ entry.message }}</span>
      </div>
      <div v-if="!filteredLogs.length" class="log-empty">暂无日志（开始建造后显示 bot 实时活动）</div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useSocketIO } from '@/composables/useSocketIO'
import { mapArtApi } from '@/api/mapArt'

/**
 * 实时日志终端（2026-08-14）：
 * 材料列表下方，实时反馈「什么时间、哪个 bot、在做什么」——补货（缺少材料→传送→
 * 寻路→开箱→取货→返回）、建造、食物、错误，颜色区分 info/warn/error。
 * 双通道：socket build_log/build_log_history 实时推送 + REST /logs 每 3s 轮询兜底
 * （防 socket 事件丢失/浏览器缓存导致终端空白）。
 * 双模式（2026-08-14）：简略=只显示 info/warn/error；详细=全部含 debug（所有操作细节）。
 */
const props = defineProps<{ taskId: string }>()
const { on: sockOn, off: sockOff, connect: sockConnect } = useSocketIO()

const logs = ref<any[]>([])
const autoScroll = ref(true)
const detailMode = ref(false)
const logBody = ref<HTMLElement>()
// 2026-08-19：per-bot 日志筛选（'' = 全部/全局事件流）
const selectedBot = ref('')
let pollTimer: number | undefined

/** 日志中出现过的 bot 列表（按首次出现顺序去重） */
const botIds = computed(() => {
  const seen: string[] = []
  for (const l of logs.value) {
    const id = l.bot_id || l.bot_name || ''
    if (id && !seen.includes(id)) seen.push(id)
  }
  return seen
})

function botName(bid: string): string {
  const hit = logs.value.find((l: any) => (l.bot_id || l.bot_name) === bid)
  return hit?.bot_name || hit?.bot_id || bid
}

/** 简略模式过滤掉 debug（详细模式显示全部） + bot 筛选（per-bot 独立终端） */
const filteredLogs = computed(() => {
  let list = logs.value
  if (selectedBot.value) {
    list = list.filter((l: any) => (l.bot_id || l.bot_name) === selectedBot.value)
  }
  if (detailMode.value) return list
  return list.filter((l: any) => l.level !== 'debug')
})

function formatTime(ts: string): string {
  if (!ts) return '--:--:--'
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight
  })
}

function appendLog(entry: any) {
  logs.value.push(entry)
  // 限制 500 条，防内存无限增长
  if (logs.value.length > 500) logs.value = logs.value.slice(-500)
  if (autoScroll.value) scrollToBottom()
}

function onLog(data: any) {
  if (data.task_id !== props.taskId) return
  appendLog(data)
}

/**
 * A3/A4：订阅（build_map_join）或控制被后端拒绝时回 build_alert——
 * 原先前端无任何订阅方，用户只看到「页面正常但永远不刷新」。
 * 这里落到终端里（错误红字），与页面层的 ElMessage 形成双通道可见反馈。
 */
function onBuildAlert(data: any) {
  const level = data?.type === 'error' ? 'error' : 'warn'
  appendLog({
    ts: new Date().toISOString(),
    level,
    bot_id: '',
    bot_name: '',
    // bot_name 留空：避免「系统」被当成一个 bot 出现在上面的 per-bot 筛选按钮里
    message: `[系统] ${data?.message || '建造实时通道异常'}`,
  })
}

function onLogHistory(data: any) {
  if (data.task_id !== props.taskId) return
  logs.value = [...(data.logs || [])]
  if (autoScroll.value) scrollToBottom()
}

function clearLog() {
  logs.value = []
}

/** REST 轮询兜底：每 3s 拉取后端日志缓冲，增量追加（按 ts+message 去重） */
async function pollLogs() {
  if (!props.taskId) return
  try {
    const { data } = await mapArtApi.getLogs(props.taskId)
    const remote = (data.logs || []) as any[]
    if (!remote.length) return
    const localKeys = new Set(logs.value.map((l: any) => `${l.ts}|${l.message}`))
    let added = false
    for (const entry of remote) {
      if (!localKeys.has(`${entry.ts}|${entry.message}`)) {
        logs.value.push(entry)
        added = true
      }
    }
    if (added) {
      if (logs.value.length > 500) logs.value = logs.value.slice(-500)
      if (autoScroll.value) scrollToBottom()
    }
  } catch {
    /* 静默：任务未运行/网络失败不影响 */
  }
}

onMounted(() => {
  // 确保 socket 已连接再注册（useSocketIO 单例：重复 connect 幂等；
  // on() 本身也已支持「未建连先登记、建连时补挂」，这里保持先连后挂的显式顺序）
  sockConnect()
  sockOn('build_log', onLog)
  sockOn('build_log_history', onLogHistory)
  sockOn('build_alert', onBuildAlert)
  // REST 轮询兜底（3s）
  pollTimer = window.setInterval(pollLogs, 3000)
  pollLogs()
})

onUnmounted(() => {
  sockOff('build_log', onLog)
  sockOff('build_log_history', onLogHistory)
  sockOff('build_alert', onBuildAlert)
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.build-log-panel { flex-shrink: 0; }
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.log-bot-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.log-bot-filter .el-radio-group {
  display: flex;
  flex-wrap: wrap;
}
.log-toolbar-label { font-size: 12px; color: var(--text-muted); }
.log-clear { margin-left: auto; }
.log-body {
  height: 260px;
  overflow-y: auto;
  background: var(--terminal-bg, #16161d);
  border-radius: 6px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.7;
}
.log-line {
  display: flex;
  gap: 8px;
  align-items: baseline;
  white-space: nowrap;
}
.log-time { color: #888; flex-shrink: 0; }
.log-bot {
  color: #7cb8ff;
  flex-shrink: 0;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.log-msg { color: #d6d6d6; }
.log-debug .log-msg { color: #8a8a9a; }
.log-debug .log-bot { color: #6f7f8f; }
.log-warn .log-msg { color: #e6b800; }
.log-warn .log-bot { color: #e6b800; }
.log-error .log-msg { color: #ff6b6b; }
.log-error .log-bot { color: #ff6b6b; }
.log-empty { color: #666; padding: 12px 0; text-align: center; }
</style>
