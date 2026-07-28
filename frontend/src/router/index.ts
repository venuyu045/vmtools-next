import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/components/layout/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '仪表盘' } },
      // --- Bot 管理（统一入口，合并了原 MCC 管理） ---
      { path: 'bots', name: 'Bots', component: () => import('@/views/BotManageView.vue'), meta: { title: 'Bot 管理' } },
      { path: 'bots/:id/terminal', name: 'BotTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'Bot 终端' } },
      { path: 'bots/:id/files', name: 'BotFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'Bot 文件' } },
      // --- 旧 MCC 路由（重定向到新 Bot 路由） ---
      { path: 'mcc/instances', redirect: '/bots' },
      { path: 'mcc/instances/:id/terminal', redirect: (to: any) => `/bots/${to.params.id}/terminal` },
      { path: 'mcc/instances/:id/files', redirect: (to: any) => `/bots/${to.params.id}/files` },
      { path: 'player-tracking', name: 'PlayerTracking', component: () => import('@/views/PlayerTrackingView.vue'), meta: { title: '玩家追踪' } },
      { path: 'miaomiao', name: 'Miaomiao', component: () => import('@/views/MiaomiaoView.vue'), meta: { title: '妙妙工具' } },
      { path: 'warehouses', name: 'Warehouses', component: () => import('@/views/WarehouseListView.vue'), meta: { title: '仓库管理' } },
      { path: 'warehouses/:id', name: 'WarehouseDetail', component: () => import('@/views/WarehouseDetailView.vue'), meta: { title: '仓库详情' } },
      { path: 'build', name: 'BuildTasks', component: () => import('@/views/BuildTaskListView.vue'), meta: { title: '建造任务' } },
      { path: 'build/:id', name: 'BuildTaskDetail', component: () => import('@/views/BuildTaskDetailView.vue'), meta: { title: '任务详情' } },
      { path: 'map-art/:taskId', name: 'MapArtBuild', component: () => import('@/views/MapArtBuildView.vue'), meta: { title: '地图画建造' } },
      { path: 'map-art-tasks', name: 'MapArtTasks', component: () => import('@/views/MapArtTaskList.vue'), meta: { title: '地图画任务' } },
      { path: 'logistics/waypoints', name: 'Waypoints', component: () => import('@/views/LogisticsWaypointView.vue'), meta: { title: '路径点' } },
      { path: 'logistics/drop-points', name: 'DropPoints', component: () => import('@/views/LogisticsDropPointView.vue'), meta: { title: '投放点' } },
      { path: 'logistics/templates', name: 'Templates', component: () => import('@/views/LogisticsTemplateView.vue'), meta: { title: '任务模板' } },
      { path: 'logistics/runs', name: 'Runs', component: () => import('@/views/LogisticsRunView.vue'), meta: { title: '任务运行' } },
      { path: 'config', name: 'Config', component: () => import('@/views/ConfigView.vue'), meta: { title: '系统配置' } },
      { path: 'plugins', name: 'Plugins', component: () => import('@/views/PluginView.vue'), meta: { title: '插件管理' } },
      { path: 'monitor', name: 'Monitor', component: () => import('@/views/MonitorView.vue'), meta: { title: '系统监控' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const authStore = useAuthStore()
  if (!to.meta.public && !authStore.isLoggedIn) {
    return '/login'
  }
})

export default router
