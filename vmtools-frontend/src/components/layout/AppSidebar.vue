<template>
  <div class="sidebar">
    <div class="sidebar-logo">
      <span class="logo-text">VMTools</span>
    </div>

    <nav class="sidebar-nav">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item) }"
      >
        <span class="nav-dot"></span>
        <span class="nav-label">{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="sidebar-status">
      <span class="status-dot online"></span>
      <span class="status-text">{{ botStore.onlineCount }} Bots 在线</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useBotStore } from '@/stores/bot'

const route = useRoute()
const botStore = useBotStore()

const navItems = [
  { path: '/dashboard', label: '仪表盘' },
  { path: '/bots', label: 'Bot 管理' },
  { path: '/warehouses', label: '仓库管理' },
  { path: '/build', label: '建造任务' },
  { path: '/logistics/waypoints', label: '物流管理' },
  { path: '/config', label: '系统配置' },
  { path: '/plugins', label: '插件管理' },
  { path: '/monitor', label: '系统监控' },
]

function isActive(item: { path: string }): boolean {
  return route.path === item.path ||
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
  padding: 20px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: center;
}

.logo-text {
  font-family: var(--font-pixel);
  font-size: 14px;
  color: var(--green-primary);
}

.sidebar-nav {
  flex: 1;
  padding: 12px 0;
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
}

.sidebar-status {
  padding: 16px 20px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-text {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--green-primary);
  opacity: 0.7;
}
</style>
