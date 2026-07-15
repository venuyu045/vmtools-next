<template>
  <div class="sidebar" :class="{ collapsed, 'is-mobile': isMobile }">
    <div class="sidebar-logo">
      <button class="collapse-btn" @click="emit('toggle')" :title="collapseTitle">
        <span class="collapse-icon">{{ collapseIcon }}</span>
      </button>
      <span class="logo-text" v-show="!collapsed">VMTools</span>
    </div>

    <nav class="sidebar-nav">
      <router-link
        v-for="item in navItems"
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

const props = defineProps<{
  collapsed?: boolean
  isMobile?: boolean
}>()
const emit = defineEmits<{
  toggle: []
}>()

const route = useRoute()
const botStore = useBotStore()

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

const navItems = [
  { path: '/dashboard', label: '仪表盘' },
  { path: '/bots', label: 'Bot 管理' },
  { path: '/mcc/instances', label: 'MCC 管理' },
  { path: '/player-tracking', label: '玩家追踪' },
  { path: '/warehouses', label: '仓库管理' },
  { path: '/build', label: '建造任务' },
  { path: '/logistics/waypoints', label: '物流管理' },
  { path: '/config', label: '系统配置' },
  { path: '/plugins', label: '插件管理' },
  { path: '/monitor', label: '系统监控' },
]

function isActive(item: { path: string }): boolean {
  return route.path === item.path ||
    (item.path === '/mcc/instances' && route.path.startsWith('/mcc')) ||
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
