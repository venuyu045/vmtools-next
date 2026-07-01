<template>
  <div>
    <div class="page-header">
      <h2>任务详情</h2>
      <el-button @click="$router.push('/build')">返回列表</el-button>
    </div>
    <el-card v-if="buildStore.currentTask" shadow="never">
      <h3>{{ buildStore.currentTask.projection_name || buildStore.currentTask.task_id }}</h3>
      <p>状态: {{ buildStore.currentTask.status }}</p>
      <p>当前状态: {{ buildStore.currentTask.current_state }}</p>
      <p>进度: {{ buildStore.currentTask.current_layer }}/{{ buildStore.currentTask.total_layers }} 层</p>
      <el-progress v-if="buildStore.currentTask.total_layers > 0" :percentage="Math.round(buildStore.currentTask.current_layer / buildStore.currentTask.total_layers * 100)" :stroke-width="8" style="margin-top: 16px" />
      <div v-if="buildStore.currentTask.error_message" style="margin-top: 16px; color: var(--color-error)">
        错误: {{ buildStore.currentTask.error_message }}
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useBuildStore } from '@/stores/build'

const route = useRoute()
const buildStore = useBuildStore()

onMounted(async () => {
  await buildStore.fetchTask(route.params.id as string)
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
