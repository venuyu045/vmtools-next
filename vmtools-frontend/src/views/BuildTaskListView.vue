<template>
  <div>
    <div class="page-header">
      <button class="pixel-btn" @click="$router.push('/build')">+ 新建任务</button>
    </div>
    <div v-if="buildStore.tasks.length === 0" class="empty-text mono">-- 暂无建造任务 --</div>
    <div class="task-grid">
      <BuildTaskCard
        v-for="task in buildStore.tasks"
        :key="task.task_id"
        :task="task"
        @start="handleStart"
        @pause="handlePause"
        @resume="handleResume"
        @cancel="handleCancel"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useBuildStore } from '@/stores/build'
import BuildTaskCard from '@/components/build/BuildTaskCard.vue'
import { ElMessage } from 'element-plus'

const buildStore = useBuildStore()

async function handleStart(task: any) {
  await buildStore.startTask(task.task_id)
  ElMessage.success('任务已启动')
}
async function handlePause(task: any) {
  await buildStore.pauseTask(task.build_task_id || task.task_id)
  ElMessage.success('任务已暂停')
}
async function handleResume(task: any) {
  await buildStore.resumeTask(task.build_task_id || task.task_id)
  ElMessage.success('任务已恢复')
}
async function handleCancel(task: any) {
  await buildStore.cancelTask(task.build_task_id || task.task_id)
  ElMessage.success('任务已取消')
}

onMounted(() => buildStore.fetchTasks())
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.empty-text { color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
.task-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
@media (max-width: 1000px) { .task-grid { grid-template-columns: 1fr; } }
</style>
