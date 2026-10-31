import { createApp, defineAsyncComponent } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/fonts.css'
import './styles/global.css'
import App from './App.vue'
import router from './router'

// ECharts：改成按需异步加载（v1.2 性能修复）。
// 原来在这里静态 import `vue-echarts` + `echarts/core` + 5 个组件并全局注册 v-chart，
// 而全站只有「系统监控」页用得到 → echarts 被并进入口 chunk，所有访客（登录页、
// 时装页）都要先下载约 300KB 图表库。现在全局组件指向异步包装，首次渲染
// <v-chart> 时才拉 echarts chunk；模板写法与 props 不变。
const LazyVChart = defineAsyncComponent(() => import('@/components/monitor/LazyVChart.vue'))

const app = createApp(App)
app.use(createPinia())
app.use(router)
// 中文语言包：此前未配置，ElMessageBox 的确认按钮显示英文「OK / Cancel」，
// 分页器显示「Go to / items/page」，与全站中文界面割裂（移动端确认弹窗尤其明显）。
app.use(ElementPlus, { locale: zhCn })
app.component('v-chart', LazyVChart)
app.mount('#app')
