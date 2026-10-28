<template>
  <div class="metrics-chart">
    <v-chart :option="chartOption" :style="{ height: height + 'px' }" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { MetricSample } from '@/stores/monitor'
import { useTheme } from '@/composables/useTheme'

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

const { resolved: themeResolved } = useTheme()
const isDark = computed(() => themeResolved.value === 'dark')
// 响应式窄屏判定：原实现只在 setup 时取一次 matchMedia 结果，
// 手机横竖屏切换 / 浏览器窗口缩放后图例与网格留白不会重算（轴标签被图例压住）。
const narrowQuery = window.matchMedia('(max-width: 480px)')
const isNarrowRef = ref(narrowQuery.matches)
const onNarrowChange = (e: MediaQueryListEvent) => { isNarrowRef.value = e.matches }
narrowQuery.addEventListener('change', onNarrowChange)
onBeforeUnmount(() => narrowQuery.removeEventListener('change', onNarrowChange))
const isNarrow = computed(() => isNarrowRef.value)

const chartOption = computed(() => {
  // 图表配色跟随主题（亮：暖米底 + 深灰文字；暗：暖墨底 + 浅色文字）
  const axisColor = isDark.value ? '#3A3830' : '#C9C5BA'
  const labelColor = isDark.value ? '#9D9A91' : '#6B6860'
  const gridColor = isDark.value ? '#2E2D27' : 'rgba(20, 20, 19, 0.06)'
  const tipBg = isDark.value ? '#2C2B26' : '#FBF9F4'
  const tipBorder = isDark.value ? '#3A3830' : '#D8D5CC'
  const tipText = isDark.value ? '#EAE7DC' : '#141413'
  const tipMuted = isDark.value ? '#9D9A91' : '#6B6860'

  const timestamps = props.metrics.map(m => new Date(m.timestamp * 1000).toLocaleTimeString())
  const cpuData = props.metrics.map(m => m.cpu_percent)
  const memData = props.metrics.map(m => m.memory_percent)
  const diskData = props.metrics.map(m => m.disk_percent)
  const netSent = props.metrics.map(m => toKbps(m.net_sent_rate))
  const netRecv = props.metrics.map(m => toKbps(m.net_recv_rate))

  return {
    backgroundColor: 'transparent',
    textStyle: { color: labelColor },
    tooltip: {
      trigger: 'axis',
      backgroundColor: tipBg,
      borderColor: tipBorder,
      textStyle: { color: tipText, fontSize: 12 },
      formatter: (params: any[]) => {
        const i = params?.[0]?.dataIndex ?? 0
        const m = props.metrics[i]
        if (!m) return ''
        const lines = params.map(p => `${p.marker} ${p.seriesName}: ${p.value}`).join('<br/>')
        const abs = m.memory_total
          ? `<br/><span style="color:${tipMuted}">内存: ${fmtBytes(m.memory_used)} / ${fmtBytes(m.memory_total)}</span>`
          : ''
        const absD = m.disk_total
          ? `<br/><span style="color:${tipMuted}">磁盘: ${fmtBytes(m.disk_used)} / ${fmtBytes(m.disk_total)}</span>`
          : ''
        return `<b>${new Date(m.timestamp * 1000).toLocaleTimeString()}</b><br/>${lines}${abs}${absD}`
      },
    },
    legend: {
      data: ['CPU', '内存', '磁盘', '上行', '下行'],
      textStyle: { color: labelColor, fontSize: isNarrow ? 10 : 12 },
      top: 0,
      // 窄屏图例项多时会换行（5 项 × 约 46px > 330px 可用宽），
      // 单行 itemGap 过大导致第二行压到坐标轴，收窄间距并允许换行。
      itemGap: isNarrow ? 8 : 10,
      itemWidth: isNarrow ? 12 : 14,
      itemHeight: isNarrow ? 8 : 10,
    },
    grid: {
      left: isNarrow ? 36 : 50,
      right: isNarrow ? 30 : 50,
      // 顶部留白：图例换行到两排时（窄屏）预留约 2 行高度，避免与网格重叠
      top: isNarrow ? 56 : 40,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: timestamps,
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: labelColor, fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value',
        name: '%',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: axisColor } },
        axisLabel: { color: labelColor, formatter: '{value}%' },
        splitLine: { lineStyle: { color: gridColor } },
      },
      {
        type: 'value',
        name: 'KB/s',
        min: 0,
        axisLine: { show: false },
        axisLabel: { color: labelColor, formatter: '{value}' },
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