<template>
  <div class="build-card pixel-card">
    <div class="build-header">
      <span :class="['status-dot', statusClass]"></span>
      <span class="build-name">{{ task.name || task.projection_name || task.task_id }}</span>
      <span :class="['pixel-badge', statusBadgeClass]">
        <span class="badge-dot"></span>
        {{ statusLabel }}
      </span>
    </div>
    <div class="build-meta mono">
      Bot: {{ task.bot_id || task.assigned_bot_id }}
      &nbsp;·&nbsp; 投影: {{ task.projection_name || '-' }}
      &nbsp;·&nbsp; 层: {{ task.current_layer }}/{{ task.total_layers }}
    </div>
    <div class="pixel-progress">
      <div class="pixel-progress-fill green" :style="{ width: progress + '%' }"></div>
    </div>
    <span class="pixel" style="font-size: 12px; margin-top: 8px; display: inline-block;">{{ progress }}%</span>
    <div class="build-actions">
      <button v-if="task.status === 'pending'" class="pixel-btn" @click="$emit('start', task)">启动</button>
      <button v-if="task.status === 'running'" class="pixel-btn warning" @click="$emit('pause', task)">暂停</button>
      <button v-if="task.status === 'paused'" class="pixel-btn outline" @click="$emit('resume', task)">继续</button>
      <button v-if="['running','paused'].includes(task.status)" class="pixel-btn danger" @click="$emit('cancel', task)">停止</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ task: any }>()
defineEmits(['start', 'pause', 'resume', 'cancel'])

const progress = computed(() => {
  if (props.task.total_layers > 0) return Math.round(props.task.current_layer / props.task.total_layers * 100)
  return props.task.progress || 0
})

const statusClass = computed(() => {
  const map: Record<string, string> = { running: 'online', paused: 'warning', pending: 'offline', completed: 'online', failed: 'error' }
  return map[props.task.status] || 'offline'
})

const statusBadgeClass = computed(() => {
  const map: Record<string, string> = { running: 'green', paused: 'yellow', pending: 'red', completed: 'green', failed: 'red' }
  return map[props.task.status] || 'red'
})

const statusLabel = computed(() => {
  const map: Record<string, string> = { running: '运行中', paused: '已暂停', pending: '待启动', completed: '已完成', failed: '失败' }
  return map[props.task.status] || '未知'
})
</script>

<style scoped>
.build-card { margin-bottom: 16px; }
.build-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.build-name { font-size: 16px; font-weight: bold; flex: 1; color: var(--text-primary); }
.build-meta { color: var(--text-secondary); font-size: 14px; margin-bottom: 12px; }
.build-actions { margin-top: 12px; display: flex; gap: 8px; }
.build-actions .pixel-btn { flex: 1; padding: 8px 0; font-size: 13px; }
</style>
