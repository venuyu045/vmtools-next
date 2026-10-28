import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/fonts.css'
import './styles/global.css'
import App from './App.vue'
import router from './router'

// ECharts
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

const app = createApp(App)
app.use(createPinia())
app.use(router)
// 中文语言包：此前未配置，ElMessageBox 的确认按钮显示英文「OK / Cancel」，
// 分页器显示「Go to / items/page」，与全站中文界面割裂（移动端确认弹窗尤其明显）。
app.use(ElementPlus, { locale: zhCn })
app.component('v-chart', VChart)
app.mount('#app')
