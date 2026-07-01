<template>
  <div>
    <h2>系统监控</h2>
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="16">
        <el-card shadow="never">
          <h3>系统指标</h3>
          <MetricsChart :metrics="monitorStore.metrics" :height="300" style="margin-top: 12px" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <h3>告警规则</h3>
          <div v-if="monitorStore.alerts.length > 0" style="margin-top: 12px">
            <div v-for="(alert, i) in monitorStore.alerts" :key="i" style="padding: 8px 0; border-bottom: 1px solid var(--border-subtle)">
              <span :class="['severity', alert.severity]">{{ alert.severity }}</span>
              {{ alert.name }}: {{ alert.metric_name }} {{ alert.operator }} {{ alert.threshold }}
            </div>
          </div>
          <EmptyState v-else message="暂无告警规则" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useMonitorStore } from '@/stores/monitor'
import MetricsChart from '@/components/monitor/MetricsChart.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const monitorStore = useMonitorStore()

onMounted(async () => {
  await monitorStore.fetchMetrics(50)
  await monitorStore.fetchAlerts()
})
</script>

<style scoped>
.severity {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  margin-right: 8px;
}
.severity.warning { background: rgba(250, 173, 20, 0.2); color: var(--color-warning); }
.severity.error { background: rgba(255, 77, 79, 0.2); color: var(--color-error); }
</style>
