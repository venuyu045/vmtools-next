import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

/** 权限常量：与后端 role 字段对应（权限组重构后：user / admin / site_admin / guest） */
export const ROLES = {
  member: ['user', 'guest'],          // 用户层级（用户 + 访客）
  admin: ['admin', 'site_admin'],     // 管理员及以上
  siteAdmin: ['site_admin'],          // 仅站点管理员
} as const

/** 所有登录用户可见的默认角色集合 */
const ALL_LOGGED_IN = [...ROLES.member, ...ROLES.admin, ...ROLES.siteAdmin]

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { public: true },
  },
  // ── 理想乡组织官网（访客完全开放，无需登录）──
  {
    path: '/lixiangxiang',
    name: 'Lixiangxiang',
    component: () => import('@/views/lixiangxiang/LixiangxiangHome.vue'),
    meta: { public: true, title: '理想乡' },
  },
  // ── 理想乡后台管理（仅管理员 admin / site_admin）──
  {
    path: '/lixiangxiang/admin',
    name: 'LixiangxiangAdmin',
    component: () => import('@/views/lixiangxiang/LixiangxiangAdmin.vue'),
    meta: { roles: [...ROLES.admin, ...ROLES.siteAdmin], title: '理想乡管理' },
  },
  {
    path: '/',
    component: () => import('@/components/layout/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      // 妙妙工具：访客无需登录即可访问（public），
      // 已登录用户（任意权限组）在布局内正常显示其权限组侧边栏；
      // 访客模式由 AppLayout 隐藏侧边栏/头部（纯内容浏览）。
      { path: 'miaomiao', name: 'Miaomiao', component: () => import('@/views/MiaomiaoView.vue'), meta: { title: '妙妙工具', public: true } },
      // --- 用户可见（总览+工具：访客只读可访问，交互即跳登录） ---
      // guestReadable：未登录访客可浏览（只读），登录用户按 roles 正常显示
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '仪表盘', roles: ALL_LOGGED_IN, guestReadable: true } },
      { path: 'player-tracking', name: 'PlayerTracking', component: () => import('@/views/PlayerTrackingView.vue'), meta: { title: '玩家列表', roles: ALL_LOGGED_IN, guestReadable: true } },
      // 上下线提醒（管理栏，独立入口）——追踪配置 + 上下线事件
      { path: 'player-alerts', name: 'PlayerAlerts', component: () => import('@/views/PlayerAlertsView.vue'), meta: { title: '上下线提醒', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'warehouse-status', name: 'WarehouseStatus', component: () => import('@/views/WarehouseStatusView.vue'), meta: { title: '仓库状态', roles: ALL_LOGGED_IN, guestReadable: true } },
      { path: 'warehouse-status/:id', name: 'WarehouseItems', component: () => import('@/views/WarehouseItemsView.vue'), meta: { title: '仓库物品', roles: ALL_LOGGED_IN, guestReadable: true } },
      // 任务中心（工具组）：地图画+物流统一任务列表与 Bot 执行/排队视角；访客只读可浏览
      { path: 'tasks', name: 'TaskCenter', component: () => import('@/views/TaskCenterView.vue'), meta: { title: '任务中心', roles: ALL_LOGGED_IN, guestReadable: true } },
      // 时装中心（VMFashion mod）：独立子应用——进入后侧边栏只保留时装内容
      // （时装商店 / 我的衣柜 / 时装管理）。由 AppLayout 依据 meta.fashionCenter
      // 切换到 FashionSidebar。入口在顶部「个人中心那一排」（AppHeader）。
      { path: 'fashion', redirect: '/fashion/store' },
      { path: 'fashion/store', name: 'FashionStore', component: () => import('@/views/fashion/FashionStoreView.vue'), meta: { title: '时装商店', roles: ALL_LOGGED_IN, fashionCenter: true } },
      { path: 'fashion/wardrobe', name: 'FashionWardrobe', component: () => import('@/views/fashion/FashionWardrobeView.vue'), meta: { title: '我的衣柜', roles: ALL_LOGGED_IN, fashionCenter: true } },
      { path: 'fashion/bind', name: 'FashionBind', component: () => import('@/views/fashion/FashionBindView.vue'), meta: { title: '时装绑定', roles: ALL_LOGGED_IN, fashionCenter: true } },
      // 时装管理端：后端是 require_site_admin（不是 require_admin）→ 必须用 ROLES.siteAdmin，
      // 否则 admin 能进页面但每个接口都 403。
      { path: 'fashion/admin', name: 'FashionAdmin', component: () => import('@/views/fashion/FashionAdminView.vue'), meta: { title: '时装管理', roles: [...ROLES.siteAdmin], fashionCenter: true } },

      // --- 管理员及以上可见 ---
      // 任务管理（管理组第一个，2026-08-13）：自定义 MF 手动工作标记，被标记 bot 不被自动调度派活
      { path: 'task-manage', name: 'TaskManage', component: () => import('@/views/TaskManageView.vue'), meta: { title: '任务管理', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'mcc-instances', name: 'MccInstances', component: () => import('@/views/BotManageView.vue'), meta: { title: 'MCC 管理', engine: 'mcc', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
    { path: 'mcc-status', name: 'MccStatus', component: () => import('@/views/BotStatusView.vue'), props: { engine: 'mcc', title: 'MCC 状态' }, meta: { title: 'MCC 状态', roles: ALL_LOGGED_IN, guestReadable: true } },
    { path: 'mf-status', name: 'MfStatus', component: () => import('@/views/BotStatusView.vue'), props: { engine: 'mineflayer', title: 'MF 状态' }, meta: { title: 'MF 状态', roles: ALL_LOGGED_IN, guestReadable: true } },
    { path: 'mf-instances', name: 'MfInstances', component: () => import('@/views/BotManageView.vue'), meta: { title: 'MF 管理', engine: 'mineflayer', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
    // MCC/MF 实例的终端/文件视图（共用视图组件，按实例 bot_engine 动态返回对应列表）
    { path: 'mcc-instances/:id/terminal', name: 'MccTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'MCC 终端', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
    { path: 'mcc-instances/:id/files', name: 'MccFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'MCC 文件', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
    { path: 'mf-instances/:id/terminal', name: 'MfTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'MF 终端', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
    { path: 'mf-instances/:id/files', name: 'MfFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'MF 文件', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'warehouses', name: 'Warehouses', component: () => import('@/views/WarehouseListView.vue'), meta: { title: '仓库管理', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'warehouses/:id', name: 'WarehouseDetail', component: () => import('@/views/WarehouseDetailView.vue'), meta: { title: '仓库详情', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'map-art/:taskId', name: 'MapArtBuild', component: () => import('@/views/MapArtBuildView.vue'), meta: { title: '地图画建造', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'map-art-tasks', name: 'MapArtTasks', component: () => import('@/views/MapArtTaskList.vue'), meta: { title: '地图画任务', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      // 旧建造任务入口 → 合并到地图画建造
      { path: 'build', redirect: '/map-art-tasks' },
      { path: 'build/:id', redirect: '/map-art-tasks' },
      { path: 'logistics/waypoints', name: 'Waypoints', component: () => import('@/views/LogisticsWaypointView.vue'), meta: { title: '路径点', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'logistics/drop-points', name: 'DropPoints', component: () => import('@/views/LogisticsDropPointView.vue'), meta: { title: '投放点', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'logistics/templates', name: 'Templates', component: () => import('@/views/LogisticsTemplateView.vue'), meta: { title: '任务模板', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'logistics/runs', name: 'Runs', component: () => import('@/views/LogisticsRunView.vue'), meta: { title: '任务运行', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },

      // --- 管理员及以上可见 ---
      // 旧 Bot 管理路由（拆分后重定向到 MCC 管理）
      { path: 'bots', redirect: '/mcc-instances' },
      { path: 'bots/:id/terminal', name: 'BotTerminal', component: () => import('@/views/MccTerminalView.vue'), meta: { title: 'Bot 终端', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },
      { path: 'bots/:id/files', name: 'BotFiles', component: () => import('@/views/MccFileManagerView.vue'), meta: { title: 'Bot 文件', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },

      // --- 站点管理员专属 ---
      { path: 'members', name: 'Members', component: () => import('@/views/MembersView.vue'), meta: { title: '成员管理', roles: [...ROLES.siteAdmin] } },
      { path: 'config', name: 'Config', component: () => import('@/views/ConfigView.vue'), meta: { title: '系统配置', roles: [...ROLES.siteAdmin] } },
      { path: 'plugins', name: 'Plugins', component: () => import('@/views/PluginView.vue'), meta: { title: '插件管理', roles: [...ROLES.siteAdmin] } },
      { path: 'plugins/:name/config', name: 'PluginConfig', component: () => import('@/views/PluginConfigView.vue'), meta: { title: '插件配置', roles: [...ROLES.siteAdmin] } },
      { path: 'monitor', name: 'Monitor', component: () => import('@/views/MonitorView.vue'), meta: { title: '系统监控', roles: [...ROLES.admin, ...ROLES.siteAdmin] } },

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

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  // 未登录（访客）：public 与 guestReadable（总览/工具只读页）放行，
  // 其余受限区域跳登录页并提示「前面的区域以后再来探索吧」
  if (!to.meta.public && !to.meta.guestReadable && !authStore.isLoggedIn) {
    return { path: '/login', query: { reason: 'locked' } }
  }

  // 刷新 / 直接输 URL 时 state.user 还是 null：必须先补齐用户信息再做角色判定。
  // 原实现 `allowedRoles && authStore.user` 在 user 为 null 时整段跳过 →
  // 管理页先渲染、再被接口 403（一闪而过的报错；admin 还能短暂看到管理端骨架）。
  if (authStore.isLoggedIn && !authStore.user) {
    await authStore.ensureUser()
  }

  // 角色路由守卫：登录用户无权访问时，回落到其有权限的首页
  const allowedRoles = to.meta.roles as string[] | undefined
  if (allowedRoles) {
    if (!authStore.user) {
      // token 失效 / 拉不到用户信息：按未登录处理，别把受限页面放出去
      if (!to.meta.public && !to.meta.guestReadable) {
        return { path: '/login', query: { reason: 'locked' } }
      }
      return
    }
    if (!allowedRoles.includes(authStore.user.role)) {
      return '/dashboard'
    }
  }
})

// 路由标题：原来全站 <title> 永远是 index.html 里的固定文案，
// 多标签页无法区分、收藏/分享也没有页面标识（meta.title 已逐条写好，只是没人用）。
router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} · VMTools` : 'VMTools · VenusYu 的网站'
})

export default router