<template>
  <div>
    <el-table :data="data" style="width: 100%">
      <el-table-column prop="run_id" label="ID" width="280" show-overflow-tooltip />
      <el-table-column prop="template_id" label="模板" width="280" show-overflow-tooltip />
      <el-table-column prop="bot_id" label="Bot" width="150" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <StatusDot :status="row.status" />
          {{ row.status }}
        </template>
      </el-table-column>
      <el-table-column label="进度" width="120">
        <template #default="{ row }">
          <span class="mono">{{ Math.round(row.progress * 100) }}%</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'running'" size="small" type="warning" @click="$emit('pause', row)">暂停</el-button>
          <el-button v-if="row.status === 'paused'" size="small" type="primary" @click="$emit('resume', row)">恢复</el-button>
          <el-button v-if="row.status === 'running' || row.status === 'paused'" size="small" type="danger" @click="$emit('stop', row)">停止</el-button>
          <el-button size="small" @click="$emit('logs', row)">日志</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import StatusDot from '@/components/common/StatusDot.vue'

defineProps<{ data: any[] }>()
defineEmits(['pause', 'resume', 'stop', 'logs'])
</script>
