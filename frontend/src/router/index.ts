import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

/** 权限常量：与后端 role 字段对应 */
export const ROLES = {
  member: ['org_member', 'user', 'guest'], // 组织成员层级
  orgAdmin: ['org_admin', 'site_admin'],   // 组织管理员及以上
  siteAdmin: ['site_admin'],               // 仅站点管理员
} as const

/** 所有登录用户可见的默认角色集合 */
const ALL_LOGGED_IN = [...ROLES.member, ...ROLES.orgAdmin, ...ROLES.siteAdmin]

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
      // --- 组织成员可见 ---
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '仪表盘', roles: ALL_LOGGED_IN } },
      { path: 'player-tracking', name: 'PlayerTracking', component: () => import('@/views/PlayerTrackingView.vue'), meta: { title: '玩家追踪', roles: ALL_LOGGED_IN } },
      { path: 'miaomiao', name: 'Miaomiao', component: () => import('@/views/MiaomiaoView.vue'), meta: { title: '妙妙工具', roles: ALL_LOGGED_IN } },

      // --- 组织管理员及以上可见 ---
      { path: 'mcc-instances', name: 'MccInstances', component: () => import('@/views/BotManageView.vue'), meta: { title: 'MCC 管理', engine: 'mcc', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
    { path: 'mf-instances', name: 'MfInstances', component: () => import('@/views/BotManageView.vue'), meta: { title: 'MF 管理', engine: 'mineflayer', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
    // MCC/MF 实例的终端/文件视图（共用视图组件，按实例 bot_engine 动态返回对应列表）
    { path: 'mcc-instances/:id/terminal', name: 'MccTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'MCC 终端', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
    { path: 'mcc-instances/:id/files', name: 'MccFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'MCC 文件', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
    { path: 'mf-instances/:id/terminal', name: 'MfTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'MF 终端', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
    { path: 'mf-instances/:id/files', name: 'MfFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'MF 文件', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'warehouses', name: 'Warehouses', component: () => import('@/views/WarehouseListView.vue'), meta: { title: '仓库管理', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'warehouses/:id', name: 'WarehouseDetail', component: () => import('@/views/WarehouseDetailView.vue'), meta: { title: '仓库详情', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'map-art/:taskId', name: 'MapArtBuild', component: () => import('@/views/MapArtBuildView.vue'), meta: { title: '地图画建造', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'map-art-tasks', name: 'MapArtTasks', component: () => import('@/views/MapArtTaskList.vue'), meta: { title: '地图画任务', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      // 旧建造任务入口 → 合并到地图画建造
      { path: 'build', redirect: '/map-art-tasks' },
      { path: 'build/:id', redirect: '/map-art-tasks' },
      { path: 'logistics/waypoints', name: 'Waypoints', component: () => import('@/views/LogisticsWaypointView.vue'), meta: { title: '路径点', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'logistics/drop-points', name: 'DropPoints', component: () => import('@/views/LogisticsDropPointView.vue'), meta: { title: '投放点', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'logistics/templates', name: 'Templates', component: () => import('@/views/LogisticsTemplateView.vue'), meta: { title: '任务模板', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'logistics/runs', name: 'Runs', component: () => import('@/views/LogisticsRunView.vue'), meta: { title: '任务运行', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },

      // --- 组织管理员及以上可见 ---
      // 旧 Bot 管理路由（拆分后重定向到 MCC 管理）
      { path: 'bots', redirect: '/mcc-instances' },
      { path: 'bots/:id/terminal', name: 'BotTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'Bot 终端', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },
      { path: 'bots/:id/files', name: 'BotFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'Bot 文件', roles: [...ROLES.orgAdmin, ...ROLES.siteAdmin] } },

      // --- 站点管理员专属 ---
      { path: 'members', name: 'Members', component: () => import('@/views/MembersView.vue'), meta: { title: '成员管理', roles: [...ROLES.siteAdmin] } },
      { path: 'config', name: 'Config', component: () => import('@/views/ConfigView.vue'), meta: { title: '系统配置', roles: [...ROLES.siteAdmin] } },
      { path: 'plugins', name: 'Plugins', component: () => import('@/views/PluginView.vue'), meta: { title: '插件管理', roles: [...ROLES.siteAdmin] } },
      { path: 'monitor', name: 'Monitor', component: () => import('@/views/MonitorView.vue'), meta: { title: '系统监控', roles: [...ROLES.siteAdmin] } },

      // --- 旧 MCC 路由（重定向到新拆分路由） ---
      { path: 'mcc/instances', redirect: '/mcc-instances' },
      { path: 'mcc/instances/:id/terminal', redirect: (to: any) => `/bots/${to.params.id}/terminal` },
      { path: 'mcc/instances/:id/files', redirect: (to: any) => `/bots/${to.params.id}/files` },
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

  // 角色路由守卫：登录用户无权访问时，回落到其有权限的首页
  const allowedRoles = to.meta.roles as string[] | undefined
  if (allowedRoles && authStore.user && !allowedRoles.includes(authStore.user.role)) {
    return '/dashboard'
  }
})

export default router