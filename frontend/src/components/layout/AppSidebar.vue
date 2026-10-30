<template>
  <div class="sidebar" :class="{ collapsed, 'is-mobile': isMobile }">
    <div class="sidebar-logo">
      <button
        class="collapse-btn"
        @click="emit('toggle')"
        :title="collapseTitle"
        :aria-label="collapseTitle"
        :aria-expanded="isMobile ? undefined : !collapsed"
      >
        <span class="collapse-icon">{{ collapseIcon }}</span>
      </button>
      <span class="logo-text" v-show="!collapsed">VMTools</span>
    </div>

    <nav class="sidebar-nav">
      <template v-for="group in visibleGroups" :key="group.title">
        <!-- 锁定分组（如 user 的管理/系统、admin 的系统）items 可能为空，但仍需渲染标题栏（锁定态，点击提示） -->
        <div class="nav-group">
          <button
            class="nav-group-title-btn"
            :class="{ locked: !group.expandable }"
            :title="group.expandable ? group.title : LOCKED_HINT"
            :disabled="collapsed"
            :aria-expanded="collapsed ? undefined : (group.expandable && expanded[group.title])"
            @click="toggleGroup(group)"
          >
            <span class="group-arrow" v-show="!collapsed">{{ group.expandable && expanded[group.title] ? '▾' : '▸' }}</span>
            <span class="group-dot" v-show="collapsed"></span>
            <span class="nav-group-title" v-show="!collapsed">{{ group.title }}</span>
          </button>
          <template v-if="!collapsed">
            <div v-show="group.expandable && expanded[group.title]" class="group-items">
              <router-link
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="nav-item"
                :class="{ active: isActive(item) }"
                :title="item.label"
                :aria-current="isActive(item) ? 'page' : undefined"
                @click="onNavClick"
              >
                <span class="nav-dot"></span>
                <span class="nav-label">{{ item.label }}</span>
              </router-link>
            </div>
          </template>
          <template v-else>
            <router-link
              v-for="item in group.items"
              :key="item.path"
              :to="item.path"
              class="nav-item"
              :class="{ active: isActive(item) }"
              :title="item.label"
              :aria-current="isActive(item) ? 'page' : undefined"
              @click="onNavClick"
            >
              <span class="nav-dot"></span>
            </router-link>
          </template>
        </div>
      </template>
    </nav>

    <div class="sidebar-status">
      <span class="status-dot online"></span>
      <span class="status-text" v-show="!collapsed">{{ botStore.onlineCount }} Bots 在线</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useBotStore } from '@/stores/bot'
import { useAuthStore } from '@/stores/auth'

/** 最小权限等级：1=用户 2=管理员 3=站点管理员 */
type MinRole = 1 | 2 | 3

interface NavItem {
  path: string
  label: string
  minRole: MinRole
}

interface NavGroup {
  title: string
  items: NavItem[]
  /** 登录用户可展开该分组所需的最低权限等级（等级 ≥ 该值才可展开） */
  expandMinRank: MinRole
  /** 访客（未登录）是否显示该分组 */
  guestVisible?: boolean
  /** 访客（未登录）是否可展开该分组 */
  guestExpandable?: boolean
}

/** 渲染时计算出的分组（附加可见/可展开状态） */
interface VisibleGroup extends NavGroup {
  visible: boolean
  expandable: boolean
}

/** 锁定分组点击提示语（未解锁区域） */
const LOCKED_HINT = '前面的区域以后再来探索吧'

/** localStorage key：分组折叠状态 */
const GROUP_STATE_KEY = 'vmtools-sidebar-group-collapsed'

const props = defineProps<{
  collapsed?: boolean
  isMobile?: boolean
}>()
const emit = defineEmits<{
  toggle: []
}>()

const route = useRoute()
const botStore = useBotStore()
const authStore = useAuthStore()

const collapseIcon = computed(() => {
  if (props.isMobile) return '✕'
  return props.collapsed ? '▶' : '◀'
})

const collapseTitle = computed(() => {
  if (props.isMobile) return '关闭菜单'
  return props.collapsed ? '展开' : '收起'
})

function onNavClick() {
  if (props.isMobile) {
    // Close drawer after navigation on mobile
    emit('toggle')
  }
}

/**
 * 侧边栏导航（抽屉式，分组可折叠）
 * - 用户(1)：仪表盘、玩家列表、妙妙工具、MCC/MF 状态、仓库状态
 * - 管理员(2)：+ MCC 管理、MF 管理、上下线提醒、仓库管理、地图画建造、物流管理、系统监控
 * - 站点管理员(3)：全部 + 成员管理、系统配置、插件管理
 *
 * 可见性规则（2026-08-12 权限可见性改造）：
 * - 访客（未登录）：显示 总览/工具/管理/系统 四栏；总览、工具、管理可展开（管理栏点击项跳登录），系统栏锁定不可展开
 * - user(1)：总览、工具可展开；管理、系统锁定（点击提示）
 * - admin(2)：总览、工具、管理可展开；系统锁定（点击提示）
 * - site_admin(3)：全部可展开
 * - 登录用户的 items 仍按 minRole 过滤；访客显示分组全部 items（点击受限项由路由守卫引导登录）
 */
const navGroups: NavGroup[] = [
  {
    title: '总览',
    expandMinRank: 1,
    guestVisible: true, // 访客保留总览（仪表盘对访客开放）
    items: [
      { path: '/dashboard', label: '仪表盘', minRole: 1 },
      // 理想乡官网入口已移至顶部横向入口（AppHeader），此处不再重复
    ],
  },
  {
    title: '工具',
    expandMinRank: 1,
    guestVisible: true,
    guestExpandable: true,
    items: [
      { path: '/player-tracking', label: '玩家列表', minRole: 1 },
      { path: '/tasks', label: '任务中心', minRole: 1 },
      // 时装相关入口已收拢到「时装中心」（顶部入口 + 专属侧边栏），此处不再显示
      { path: '/miaomiao', label: '妙妙工具', minRole: 1 },
      { path: '/mcc-status', label: 'MCC 状态', minRole: 1 },
      { path: '/mf-status', label: 'MF 状态', minRole: 1 },
      { path: '/warehouse-status', label: '仓库状态', minRole: 1 },
    ],
  },
  {
    title: '管理',
    expandMinRank: 2,
    guestVisible: true,
    guestExpandable: true,
    items: [
      { path: '/task-manage', label: '任务管理', minRole: 2 },
      { path: '/mcc-instances', label: 'MCC 管理', minRole: 2 },
      { path: '/mf-instances', label: 'MF 管理', minRole: 2 },
      { path: '/player-alerts', label: '上下线提醒', minRole: 2 },
      { path: '/warehouses', label: '仓库管理', minRole: 2 },
      { path: '/map-art-tasks', label: '地图画建造', minRole: 2 },
      { path: '/logistics/waypoints', label: '物流管理', minRole: 2 },
      { path: '/monitor', label: '系统监控', minRole: 2 },
    ],
  },
  {
    title: '系统',
    expandMinRank: 3,
    guestVisible: true,
    guestExpandable: false, // 访客始终折叠不可展开
    items: [
      { path: '/members', label: '成员管理', minRole: 3 },
      // 时装管理入口已移到「时装中心」专属侧边栏（仅站点管理员可见）
      { path: '/config', label: '系统配置', minRole: 3 },
      { path: '/plugins', label: '插件管理', minRole: 3 },
    ],
  },
]

/**
 * 当前角色可见分组：
 * - 未登录（访客）：按 guestVisible/guestExpandable 显式配置，items 全量展示（点受限项由路由守卫引导登录）
 * - 已登录：分组全部可见；可展开条件 = 角色等级 ≥ expandMinRank；items 按 minRole ≤ 角色等级过滤
 */
const visibleGroups = computed<VisibleGroup[]>(() => {
  const loggedIn = authStore.isLoggedIn
  const rank = authStore.roleRank
  return navGroups
    .map(group => {
      const visible = loggedIn ? true : (group.guestVisible ?? false)
      const expandable = loggedIn ? rank >= group.expandMinRank : (group.guestExpandable ?? false)
      const items = loggedIn
        ? group.items.filter(item => item.minRole <= rank)
        : group.items
      return { ...group, visible, expandable, items }
    })
    .filter(group => group.visible)
})

/** 分组折叠状态（默认展开，localStorage 持久化） */
const expanded = reactive<Record<string, boolean>>({})

function loadGroupState() {
  try {
    const raw = localStorage.getItem(GROUP_STATE_KEY)
    if (raw) {
      const saved: Record<string, boolean> = JSON.parse(raw)
      for (const g of navGroups) {
        expanded[g.title] = saved[g.title] !== false // 默认展开
      }
    }
  } catch { /* 忽略损坏的状态 */ }
  for (const g of navGroups) {
    if (expanded[g.title] === undefined) expanded[g.title] = true
  }
}

function toggleGroup(group: VisibleGroup) {
  if (props.collapsed) return // 整栏收起时不响应分组折叠
  if (!group.expandable) {
    // 锁定分组（未解锁区域）：不可展开，点击提示
    ElMessage.warning(LOCKED_HINT)
    return
  }
  expanded[group.title] = !expanded[group.title]
  try {
    localStorage.setItem(GROUP_STATE_KEY, JSON.stringify({ ...expanded }))
  } catch { /* 忽略 */ }
}

loadGroupState()

function isActive(item: { path: string }): boolean {
  const detailOf = (base: string): boolean =>
    route.path === base || route.path.startsWith(base + '/')
  if (item.path === '/mcc-instances') {
    // 终端/文件详情路由仍为 /bots/:id/...，归属 MCC 管理高亮
    return detailOf('/mcc-instances') || route.path.startsWith('/bots/')
  }
  if (item.path === '/mf-instances') return detailOf('/mf-instances')
  if (item.path === '/warehouses') return detailOf('/warehouses')
  if (item.path === '/map-art-tasks') {
    return detailOf('/map-art-tasks') || route.path.startsWith('/map-art/')
  }
  if (item.path === '/logistics/waypoints') return route.path.startsWith('/logistics')
  return detailOf(item.path)
}
</script>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border-right: 1px solid var(--border-subtle);
}

.sidebar-logo {
  padding: 16px 14px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 56px;
}

.collapse-btn {
  background: none;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  flex-shrink: 0;
  transition: background-color 150ms var(--ease-out), border-color 150ms var(--ease-out), color 150ms var(--ease-out);
}

.collapse-btn:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* Mobile close button: make it bigger for touch */
.is-mobile .collapse-btn {
  width: 36px;
  height: 36px;
  font-size: 16px;
}

.logo-text {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 400;
  letter-spacing: -0.5px;
  color: var(--text-primary);
  white-space: nowrap;
  transition: opacity 0.2s ease;
}

.sidebar-nav {
  flex: 1;
  padding: 12px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

/* ---- 分组（抽屉式可折叠） ---- */
.nav-group {
  display: flex;
  flex-direction: column;
  padding-top: 6px;
}

.nav-group:first-child {
  padding-top: 0;
}

/* 分组标题按钮：点击折叠/展开 */
.nav-group-title-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 14px;
  background: none;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  opacity: 0.9;
  transition: background-color 150ms var(--ease-out), color 150ms var(--ease-out);
  text-align: left;
  min-height: 34px;
}

.nav-group-title-btn:hover {
  opacity: 1;
  color: var(--accent);
  background: var(--bg-hover);
}

/* 整栏折叠（collapsed）时分组标题不可点击：置灰并禁用 hover 反馈 */
.nav-group-title-btn:disabled {
  cursor: default;
  opacity: 0.4;
}

.nav-group-title-btn:disabled:hover {
  opacity: 0.4;
  color: var(--text-muted);
  background: none;
}

/* 锁定分组（未解锁区域）：始终折叠，点击提示「前面的区域以后再来探索吧」 */
.nav-group-title-btn.locked {
  opacity: 0.55;
  cursor: pointer;
}

.nav-group-title-btn.locked:hover {
  opacity: 0.85;
  color: var(--text-muted);
  background: var(--bg-hover);
}

.nav-group-title-btn.locked .group-arrow {
  color: var(--text-muted);
}

.group-arrow {
  width: 12px;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.15s ease;
}

.nav-group-title-btn:hover .group-arrow {
  color: var(--accent);
}

.group-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.5;
  flex-shrink: 0;
}

.nav-group-title {
  white-space: nowrap;
}

.group-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  text-decoration: none;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 500;
  border-radius: var(--radius-md);
  position: relative;
  transition: background-color 150ms var(--ease-out), color 150ms var(--ease-out);
  cursor: pointer;
  /* Touch-friendly: min 44px height */
  min-height: 44px;
}

.sidebar.collapsed .nav-item {
  padding: 0;
  justify-content: center;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 2px;
  background: var(--accent);
}

.nav-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}

.nav-item:not(.active) .nav-dot {
  opacity: 0.4;
}

.nav-item.active .nav-dot {
  opacity: 1;
}

.nav-label {
  flex: 1;
  white-space: nowrap;
}

.sidebar-status {
  padding: 16px 20px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 50px;
}

.sidebar.collapsed .sidebar-status {
  padding: 16px 0;
  justify-content: center;
}

.status-text {
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-secondary);
  opacity: 0.85;
  white-space: nowrap;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  flex-shrink: 0;
}

/* Mobile drawer: no right border, full border on right for shadow depth */
.is-mobile {
  border-right: 1px solid var(--border-subtle);
}
</style>