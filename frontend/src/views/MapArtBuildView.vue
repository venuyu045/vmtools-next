<template>
  <div class="mapart-build-page">
    <!-- Header -->
    <div class="page-header">
      <h2>{{ task?.name || 'Map Art Build' }}</h2>
      <div class="header-right">
        <el-tag :type="statusTagType">{{ task?.status || 'draft' }}</el-tag>
        <span class="progress-text">{{ task?.placed_blocks ?? 0 }} / {{ task?.total_blocks ?? 0 }} blocks</span>
      </div>
    </div>

    <!-- Main content: 3D canvas + side panels -->
    <div class="main-content">
      <!-- 3D Canvas -->
      <div class="canvas-area">
        <BuildMapCanvas
          :task-id="taskId"
          :materials="materials"
          @ready="onCanvasReady"
        />

        <!-- Control bar -->
        <div class="control-bar">
          <el-button
            v-if="task?.status === 'draft' || task?.status === 'pending'"
            type="primary"
            @click="control('start')"
          >
            ▶ Start
          </el-button>
          <el-button
            v-if="task?.status === 'running'"
            @click="control('pause')"
          >
            ⏸ Pause
          </el-button>
          <el-button
            v-if="task?.status === 'paused'"
            type="success"
            @click="control('resume')"
          >
            ▶ Resume
          </el-button>
          <el-button
            v-if="task?.status === 'running' || task?.status === 'paused'"
            type="danger"
            @click="control('stop')"
          >
            ⏹ Stop
          </el-button>
        </div>
      </div>

      <!-- Right panels -->
      <div class="side-panels">
        <!-- Bot status -->
        <el-card class="panel" header="Bots">
          <div v-if="!bots.length" class="empty">No bots assigned</div>
          <div v-for="bot in bots" :key="bot.bot_id" class="bot-row">
            <div class="bot-header">
              <span class="bot-dot" :style="{ background: botColor(bot.bot_id) }" />
              <strong>{{ bot.bot_name || bot.bot_id }}</strong>
              <el-tag size="small" :type="botStateType(bot.state)">{{ bot.state }}</el-tag>
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
              <span>Row {{ bot.current_row >= 0 ? bot.current_row : '-' }}</span>
              <span>{{ (bot.rate ?? 0).toFixed(1) }} blk/min</span>
            </div>
          </div>
        </el-card>

        <!-- Materials -->
        <el-card class="panel" header="Materials">
          <div v-for="m in materials?.slice(0, 12)" :key="m.item_id" class="mat-row">
            <span class="mat-dot" :style="{ background: matColor(m.item_id) }" />
            <span class="mat-name">{{ m.display_name }}</span>
            <span class="mat-count">{{ m.placed ?? 0 }} / {{ m.required }}</span>
          </div>
        </el-card>

        <!-- Stats -->
        <el-card class="panel" header="Stats">
          <div class="stat-row">
            <span>Elapsed</span>
            <span>{{ formatTime(elapsed) }}</span>
          </div>
          <div class="stat-row">
            <span>ETA</span>
            <span>{{ formatTime(eta) }}</span>
          </div>
          <div class="stat-row">
            <span>Overall Rate</span>
            <span>{{ overallRate }} blk/min</span>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import BuildMapCanvas from '@/components/build/BuildMapCanvas.vue'
import { useSocketIO } from '@/composables/useSocketIO'
import { mapArtApi } from '@/api/mapArt'

const route = useRoute()
const taskId = computed(() => route.params.taskId as string)
const { on: sockOn, emit: sockEmit } = useSocketIO()

const task = ref<any>(null)
const bots = ref<any[]>([])
const materials = ref<any[]>([])
const elapsed = ref(0)
const eta = ref(0)
const overallRate = ref('0')

const statusTagType = computed(() => {
  const s = task.value?.status
  if (s === 'running') return 'success'
  if (s === 'completed') return ''
  if (s === 'failed') return 'danger'
  if (s === 'paused') return 'warning'
  return 'info'
})

function botStateType(state: string): string {
  if (state === 'placing') return 'success'
  if (state === 'offline' || state === 'failed') return 'danger'
  if (state === 'restocking' || state === 'moving') return 'warning'
  return 'info'
}

function botColor(botId: string): string {
  const h = botId.split('').reduce((s, c) => s + c.charCodeAt(0), 0)
  return `#${((h * 2654435761) >>> 0).toString(16).slice(0, 6)}`
}

function matColor(itemId: string): string {
  const colors: Record<string, string> = {
    'minecraft:white_wool': '#FFFFFF', 'minecraft:orange_wool': '#F9801D',
    'minecraft:magenta_wool': '#C74EBD', 'minecraft:light_blue_wool': '#3AB3DA',
    'minecraft:yellow_wool': '#FED83D', 'minecraft:lime_wool': '#80C71F',
    'minecraft:pink_wool': '#F38BAA', 'minecraft:gray_wool': '#474F52',
    'minecraft:light_gray_wool': '#9D9D97', 'minecraft:cyan_wool': '#169C9D',
    'minecraft:purple_wool': '#8932B8', 'minecraft:blue_wool': '#3C44AA',
    'minecraft:brown_wool': '#835432', 'minecraft:green_wool': '#5E7C16',
    'minecraft:red_wool': '#B02E26', 'minecraft:black_wool': '#1D1D21',
  }
  return colors[itemId] ?? '#888888'
}

function formatTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}m ${s}s`
}

function onCanvasReady() {
  // Canvas initialized
}

// ---- API calls ----

async function fetchTask() {
  try {
    const { data } = await mapArtApi.getTask(taskId.value)
    task.value = data
    materials.value = data.materials || []
    bots.value = data.bots || []
  } catch (e) {
    ElMessage.error('Failed to fetch task')
  }
}

async function control(action: string) {
  try {
    await mapArtApi.controlTask(taskId.value, action)
    ElMessage.success(`Task ${action}ed`)
    fetchTask()
  } catch (e) {
    ElMessage.error(`Failed to ${action} task`)
  }
}

// ---- Socket.IO progress updates ----

onMounted(() => {
  fetchTask()
  sockEmit('build_map_join', { task_id: taskId.value })

  sockOn('build_progress', (data: any) => {
    if (data.task_id !== taskId.value) return
    task.value = { ...task.value, status: data.status, placed_blocks: data.placed_blocks, total_blocks: data.total_blocks }
    elapsed.value = data.elapsed_sec || 0
    eta.value = data.eta_sec || 0
    overallRate.value = data.placed_blocks > 0 && data.elapsed_sec > 0
      ? (data.placed_blocks / (data.elapsed_sec / 60)).toFixed(1)
      : '0'
    if (data.materials) {
      materials.value = Object.entries(data.materials).map(([k, v]: [string, any]) => ({
        item_id: k, display_name: k.split(':')[1], placed: v.placed, required: v.required,
      }))
    }
  })

  sockOn('build_bot_status', (data: any) => {
    if (data.task_id !== taskId.value) return
    bots.value = data.bots || []
  })
})

onUnmounted(() => {
  sockEmit('build_map_leave', { task_id: taskId.value })
})
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
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.progress-text {
  color: #888;
  font-size: 14px;
}
.main-content {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 12px;
  min-height: 0;
}
.canvas-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
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
}
.panel {
  flex-shrink: 0;
}
.bot-row {
  padding: 6px 0;
  border-bottom: 1px solid #333;
}
.bot-row:last-child { border-bottom: none }
.bot-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bot-dot { width: 10px; height: 10px; border-radius: 50%; }
.bot-progress { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.bot-stats { font-size: 12px; color: #888; white-space: nowrap; }
.bot-meta { display: flex; justify-content: space-between; font-size: 11px; color: #666; }
.mat-row {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 0; font-size: 12px;
}
.mat-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.mat-name { flex: 1; }
.mat-count { color: #888; font-variant-numeric: tabular-nums; }
.stat-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.empty { color: #666; padding: 12px 0; text-align: center; }
</style>
