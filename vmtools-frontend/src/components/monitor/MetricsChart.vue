<template>
  <div class="metrics-chart">
    <v-chart :option="chartOption" :style="{ height: height + 'px' }" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MetricSample } from '@/stores/monitor'

const props = defineProps<{
  metrics: MetricSample[]
  height?: number
}>()

const chartOption = computed(() => {
  const timestamps = props.metrics.map(m => new Date(m.timestamp * 1000).toLocaleTimeString())
  const cpuData = props.metrics.map(m => m.cpu_percent)
  const memData = props.metrics.map(m => m.memory_percent)
  const diskData = props.metrics.map(m => m.disk_percent)

  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#888' },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1a1a1a',
      borderColor: 'rgba(212, 168, 67, 0.3)',
      textStyle: { color: '#e8e8e8' },
    },
    legend: {
      data: ['CPU', '内存', '磁盘'],
      textStyle: { color: '#888' },
      top: 0,
    },
    grid: {
      left: 50,
      right: 20,
      top: 40,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: timestamps,
      axisLine: { lineStyle: { color: '#333' } },
      axisLabel: { color: '#666', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLine: { lineStyle: { color: '#333' } },
      axisLabel: { color: '#666', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#222' } },
    },
    series: [
      {
        name: 'CPU',
        type: 'line',
        data: cpuData,
        smooth: true,
        lineStyle: { color: '#d4a843', width: 2 },
        itemStyle: { color: '#d4a843' },
        areaStyle: { color: 'rgba(212, 168, 67, 0.1)' },
      },
      {
        name: '内存',
        type: 'line',
        data: memData,
        smooth: true,
        lineStyle: { color: '#52c41a', width: 2 },
        itemStyle: { color: '#52c41a' },
        areaStyle: { color: 'rgba(82, 196, 26, 0.1)' },
      },
      {
        name: '磁盘',
        type: 'line',
        data: diskData,
        smooth: true,
        lineStyle: { color: '#1890ff', width: 2 },
        itemStyle: { color: '#1890ff' },
        areaStyle: { color: 'rgba(24, 144, 255, 0.1)' },
      },
    ],
  }
})
</script>

<style scoped>
.metrics-chart {
  width: 100%;
}
</style>
