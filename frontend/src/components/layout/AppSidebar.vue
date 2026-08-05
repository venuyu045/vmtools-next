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
          <span class="nav-group-title" v-show="!collapsed">{{ group.title }}</span>
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
            <span class="nav-label" v-show="!collapsed">{{ item.label }}</span>
          </router-link>
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
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useBotStore } from '@/stores/bot'
import { useAuthStore } from '@/stores/auth'

/** 最小权限等级：1=组织成员 2=组织管理员 3=站点管理员 */
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
 * 侧边栏导航（按权限分组）
 * - 组织成员(1)：仪表盘、玩家追踪、妙妙工具
 * - 组织管理员(2)：+ 仓库管理、建造任务、地图画建造、物流管理
 * - 站点管理员(3)：全部 + Bot 管理、成员管理、系统配置、插件管理、系统监控
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
      { path: '/player-tracking', label: '玩家追踪', minRole: 1 },
      { path: '/miaomiao', label: '妙妙工具', minRole: 1 },
    ],
  },
  {
    title: '管理',
    items: [
      { path: '/warehouses', label: '仓库管理', minRole: 2 },
      { path: '/build', label: '建造任务', minRole: 2 },
      { path: '/map-art-tasks', label: '地图画建造', minRole: 2 },
      { path: '/logistics/waypoints', label: '物流管理', minRole: 2 },
    ],
  },
  {
    title: '系统',
    items: [
      { path: '/bots', label: 'Bot 管理', minRole: 3 },
      { path: '/members', label: '成员管理', minRole: 3 },
      { path: '/config', label: '系统配置', minRole: 3 },
      { path: '/plugins', label: '插件管理', minRole: 3 },
      { path: '/monitor', label: '系统监控', minRole: 3 },
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

function isActive(item: { path: string }): boolean {
  return route.path === item.path ||
    (item.path === '/bots' && (route.path.startsWith('/bots') || route.path.startsWith('/mcc'))) ||
    (item.path === '/logistics/waypoints' && route.path.startsWith('/logistics'))
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

/* ---- 分组标题 ---- */
.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 8px;
}

.nav-group:first-child {
  padding-top: 0;
}

.nav-group-title {
  padding: 6px 20px 4px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
  opacity: 0.6;
  white-space: nowrap;
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
  transition: opacity 0.2s ease;
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