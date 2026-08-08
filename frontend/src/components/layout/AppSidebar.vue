<template>
  <div class="sidebar" :class="{ collapsed, 'is-mobile': isMobile }">
    <div class="sidebar-logo">
      <button class="collapse-btn" @click="emit('toggle')" :title="collapseTitle">
        <span class="collapse-icon">{{ collapseIcon }}</span>
      </button>
      <span class="logo-text" v-show="!collapsed">VMTools</span>
    </div>

    <nav class="sidebar-nav">
      <template v-for="group in visibleGroups" :key="group.title">
        <div v-if="group.items.length" class="nav-group">
          <button
            class="nav-group-title-btn"
            :title="group.title"
            @click="toggleGroup(group.title)"
          >
            <span class="group-arrow" v-show="!collapsed">{{ expanded[group.title] ? '▾' : '▸' }}</span>
            <span class="group-dot" v-show="collapsed"></span>
            <span class="nav-group-title" v-show="!collapsed">{{ group.title }}</span>
          </button>
          <template v-if="!collapsed">
            <div v-show="expanded[group.title]" class="group-items">
              <router-link
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="nav-item"
                :class="{ active: isActive(item) }"
                :title="item.label"
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
}

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
 */
const navGroups: NavGroup[] = [
  {
    title: '总览',
    items: [
      { path: '/dashboard', label: '仪表盘', minRole: 1 },
    ],
  },
  {
    title: '工具',
    items: [
      { path: '/player-tracking', label: '玩家列表', minRole: 1 },
      { path: '/miaomiao', label: '妙妙工具', minRole: 1 },
      { path: '/mcc-status', label: 'MCC 状态', minRole: 1 },
      { path: '/mf-status', label: 'MF 状态', minRole: 1 },
      { path: '/warehouse-status', label: '仓库状态', minRole: 1 },
    ],
  },
  {
    title: '管理',
    items: [
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
    items: [
      { path: '/members', label: '成员管理', minRole: 3 },
      { path: '/config', label: '系统配置', minRole: 3 },
      { path: '/plugins', label: '插件管理', minRole: 3 },
    ],
  },
]

/** 仅保留当前用户权限等级 ≥ minRole 的分组 */
const visibleGroups = computed<NavGroup[]>(() => {
  const rank = authStore.roleRank
  return navGroups
    .map(group => ({
      ...group,
      items: group.items.filter(item => item.minRole <= rank),
    }))
    .filter(group => group.items.length > 0)
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

function toggleGroup(title: string) {
  if (props.collapsed) return // 整栏收起时不响应分组折叠
  expanded[title] = !expanded[title]
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
  background: #0a0a0a;
  border-right: 2px solid var(--border-subtle);
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
  border: 1px solid var(--border-card);
  color: var(--green-primary);
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  flex-shrink: 0;
}

.collapse-btn:hover {
  border-color: var(--border-active);
  background: var(--green-glow);
  color: var(--text-primary);
}

/* Mobile close button: make it bigger for touch */
.is-mobile .collapse-btn {
  width: 36px;
  height: 36px;
  font-size: 16px;
}

.logo-text {
  font-family: var(--font-pixel);
  font-size: 14px;
  color: var(--green-primary);
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
  padding: 8px 16px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
  opacity: 0.75;
  transition: all 0.12s;
  text-align: left;
  min-height: 34px;
}

.nav-group-title-btn:hover {
  opacity: 1;
  color: var(--green-primary);
  background: var(--green-glow);
}

.group-arrow {
  width: 12px;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.15s ease;
}

.nav-group-title-btn:hover .group-arrow {
  color: var(--green-primary);
}

.group-dot {
  width: 6px;
  height: 6px;
  background: var(--green-primary);
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
  padding: 10px 20px;
  text-decoration: none;
  color: var(--text-secondary);
  font-family: var(--font-body);
  font-size: 14px;
  transition: all 0.1s;
  cursor: pointer;
  /* Touch-friendly: min 44px height */
  min-height: 44px;
}

.sidebar.collapsed .nav-item {
  padding: 10px 0;
  justify-content: center;
}

.nav-item:hover {
  background: var(--green-glow);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--green-glow);
  color: var(--green-primary);
}

.nav-dot {
  width: 6px;
  height: 6px;
  background: var(--green-primary);
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
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--green-primary);
  opacity: 0.7;
  white-space: nowrap;
}

.status-dot {
  width: 8px;
  height: 8px;
  background: var(--green-primary);
  flex-shrink: 0;
}

/* Mobile drawer: no right border, full border on right for shadow depth */
.is-mobile {
  border-right: 1px solid var(--border-subtle);
}
</style>