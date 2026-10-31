<template>
  <v-chart :option="option" autoresize />
</template>

<script setup lang="ts">
/**
 * ECharts 懒加载包装（v1.2 性能修复）。
 *
 * 背景：`main.ts` 原来把 `vue-echarts` + `echarts/core` + 5 个组件静态 import 并全局注册
 * `v-chart`，而全站只有 `components/monitor/MetricsChart.vue` 用得上 → echarts 被并进
 * 入口 chunk，所有访客（含登录页、时装页）都要先下载约 300KB 的图表库。
 *
 * 现在 `main.ts` 用 `defineAsyncComponent(() => import('@/components/monitor/LazyVChart.vue'))`
 * 注册同名全局组件：只有真正打开「系统监控」页时才加载 echarts chunk，
 * 模板里的 `<v-chart>` 写法与传参完全不用改。
 */
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

defineProps<{ option: Record<string, unknown> }>()
</script>
