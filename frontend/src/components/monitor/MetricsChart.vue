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

/** bytes → 可读（KB/MB） */
function fmtBytes(n: number): string {
  if (!n || n <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(1) + ' ' + units[i]
}

/** bytes/s → KB/s */
function toKbps(n: number | undefined): number {
  return ((n || 0) / 1024).toFixed(1) as unknown as number
}

const chartOption = computed(() => {
  const timestamps = props.metrics.map(m => new Date(m.timestamp * 1000).toLocaleTimeString())
  const cpuData = props.metrics.map(m => m.cpu_percent)
  const memData = props.metrics.map(m => m.memory_percent)
  const diskData = props.metrics.map(m => m.disk_percent)
  const netSent = props.metrics.map(m => toKbps(m.net_sent_rate))
  const netRecv = props.metrics.map(m => toKbps(m.net_recv_rate))

  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#888' },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0a0a0a',
      borderColor: 'rgba(0, 255, 0, 0.3)',
      textStyle: { color: '#e8e8e8', fontSize: 12 },
      formatter: (params: any[]) => {
        const i = params?.[0]?.dataIndex ?? 0
        const m = props.metrics[i]
        if (!m) return ''
        const lines = params.map(p => `${p.marker} ${p.seriesName}: ${p.value}`).join('<br/>')
        const abs = m.memory_total
          ? `<br/><span style="color:#666">内存: ${fmtBytes(m.memory_used)} / ${fmtBytes(m.memory_total)}</span>`
          : ''
        const absD = m.disk_total
          ? `<br/><span style="color:#666">磁盘: ${fmtBytes(m.disk_used)} / ${fmtBytes(m.disk_total)}</span>`
          : ''
        return `<b>${new Date(m.timestamp * 1000).toLocaleTimeString()}</b><br/>${lines}${abs}${absD}`
      },
    },
    legend: {
      data: ['CPU', '内存', '磁盘', '上行', '下行'],
      textStyle: { color: '#888' },
      top: 0,
    },
    grid: {
      left: 50,
      right: 50,
      top: 40,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: timestamps,
      axisLine: { lineStyle: { color: '#333' } },
      axisLabel: { color: '#666', fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value',
        name: '%',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#666', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#222' } },
      },
      {
        type: 'value',
        name: 'KB/s',
        min: 0,
        axisLine: { show: false },
        axisLabel: { color: '#666', formatter: '{value}' },
        splitLine: { show: false },
      },
    ],
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
      {
        name: '上行',
        type: 'line',
        yAxisIndex: 1,
        data: netSent,
        smooth: true,
        lineStyle: { color: '#ff7875', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#ff7875' },
        symbolSize: 3,
      },
      {
        name: '下行',
        type: 'line',
        yAxisIndex: 1,
        data: netRecv,
        smooth: true,
        lineStyle: { color: '#69a7ff', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#69a7ff' },
        symbolSize: 3,
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