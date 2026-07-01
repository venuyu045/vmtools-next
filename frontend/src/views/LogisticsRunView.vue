<template>
  <div>
    <div class="page-header">
      <h2>任务运行</h2>
    </div>
    <RunTable :data="logisticsStore.runs" @pause="handlePause" @resume="handleResume" @stop="handleStop" @logs="handleLogs" />
    <EmptyState v-if="logisticsStore.runs.length === 0" message="暂无运行中的任务" />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useLogisticsStore } from '@/stores/logistics'
import RunTable from '@/components/logistics/RunTable.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { ElMessage } from 'element-plus'

const logisticsStore = useLogisticsStore()

async function handlePause(row: any) {
  await logisticsStore.pauseTask(row.run_id)
  ElMessage.success('已暂停')
}

async function handleResume(row: any) {
  await logisticsStore.resumeTask(row.run_id)
  ElMessage.success('已恢复')
}

async function handleStop(row: any) {
  await logisticsStore.stopTask(row.run_id)
  ElMessage.success('已停止')
}

function handleLogs(row: any) {
  ElMessage.info('日志功能待实现')
}

onMounted(() => logisticsStore.fetchRuns())
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
