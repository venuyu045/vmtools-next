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
    textStyle: { color: '#9D9A91' },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#2C2B26',
      borderColor: '#3A3830',
      textStyle: { color: '#EAE7DC', fontSize: 12 },
      formatter: (params: any[]) => {
        const i = params?.[0]?.dataIndex ?? 0
        const m = props.metrics[i]
        if (!m) return ''
        const lines = params.map(p => `${p.marker} ${p.seriesName}: ${p.value}`).join('<br/>')
        const abs = m.memory_total
          ? `<br/><span style="color:#9D9A91">内存: ${fmtBytes(m.memory_used)} / ${fmtBytes(m.memory_total)}</span>`
          : ''
        const absD = m.disk_total
          ? `<br/><span style="color:#9D9A91">磁盘: ${fmtBytes(m.disk_used)} / ${fmtBytes(m.disk_total)}</span>`
          : ''
        return `<b>${new Date(m.timestamp * 1000).toLocaleTimeString()}</b><br/>${lines}${abs}${absD}`
      },
    },
    legend: {
      data: ['CPU', '内存', '磁盘', '上行', '下行'],
      textStyle: { color: '#9D9A91' },
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
      axisLine: { lineStyle: { color: '#3A3830' } },
      axisLabel: { color: '#9D9A91', fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value',
        name: '%',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: '#3A3830' } },
        axisLabel: { color: '#9D9A91', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#2E2D27' } },
      },
      {
        type: 'value',
        name: 'KB/s',
        min: 0,
        axisLine: { show: false },
        axisLabel: { color: '#9D9A91', formatter: '{value}' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'CPU',
        type: 'line',
        data: cpuData,
        smooth: true,
        lineStyle: { color: '#D97757', width: 2 },
        itemStyle: { color: '#D97757' },
        areaStyle: { color: 'rgba(217, 119, 87, 0.10)' },
      },
      {
        name: '内存',
        type: 'line',
        data: memData,
        smooth: true,
        lineStyle: { color: '#8A9A5B', width: 2 },
        itemStyle: { color: '#8A9A5B' },
        areaStyle: { color: 'rgba(138, 154, 91, 0.10)' },
      },
      {
        name: '磁盘',
        type: 'line',
        data: diskData,
        smooth: true,
        lineStyle: { color: '#7C8B7E', width: 2 },
        itemStyle: { color: '#7C8B7E' },
        areaStyle: { color: 'rgba(124, 139, 126, 0.10)' },
      },
      {
        name: '上行',
        type: 'line',
        yAxisIndex: 1,
        data: netSent,
        smooth: true,
        lineStyle: { color: '#B08D57', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#B08D57' },
        symbolSize: 3,
      },
      {
        name: '下行',
        type: 'line',
        yAxisIndex: 1,
        data: netRecv,
        smooth: true,
        lineStyle: { color: '#B89B3E', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#B89B3E' },
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