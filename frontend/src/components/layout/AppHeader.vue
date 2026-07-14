<template>
  <div class="header">
    <div class="header-left">
      <!-- Mobile: hamburger menu button -->
      <button class="mobile-menu-btn show-on-mobile" @click="emit('openMobileMenu')" title="菜单" aria-label="打开菜单">
        ☰
      </button>
      <!-- Desktop: sidebar collapse toggle -->
      <button class="sidebar-toggle hide-on-mobile" @click="emit('toggleSidebar')" title="切换侧边栏" aria-label="切换侧边栏">
        ☰
      </button>
      <div class="page-title" v-if="route.meta.title">
        > {{ route.meta.title }}
      </div>
      <div class="page-title" v-else>
        > VMTools
      </div>
    </div>
    <div class="header-right">
      <span class="user-dot"></span>
      <span class="username hide-on-mobile">{{ authStore.user?.display_name || authStore.user?.game_id }}</span>
      <span class="username-mobile show-on-mobile">{{ shortName }}</span>
      <button class="logout-btn" @click="authStore.logout()" aria-label="退出登录">退出</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

defineProps<{ isMobile?: boolean }>()
const emit = defineEmits<{
  toggleSidebar: []
  openMobileMenu: []
}>()
const route = useRoute()
const authStore = useAuthStore()

const shortName = computed(() => {
  const name = authStore.user?.display_name || authStore.user?.game_id || ''
  return name.length > 8 ? name.slice(0, 8) + '...' : name
})
</script>

<style scoped>
.header {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  background: #0a0a0a;
  border-bottom: 1px solid var(--border-subtle);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0; /* allow truncation */
}

/* ---- Toggle Buttons ---- */
.sidebar-toggle,
.mobile-menu-btn {
  background: none;
  border: 1px solid var(--border-card);
  color: var(--green-primary);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 14px;
  flex-shrink: 0;
}

.sidebar-toggle:hover,
.mobile-menu-btn:hover {
  border-color: var(--border-active);
  background: var(--green-glow);
  color: var(--text-primary);
}

/* ---- Page Title ---- */
.page-title {
  font-family: var(--font-pixel);
  font-size: 16px;
  color: var(--green-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- Right Side ---- */
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.user-dot {
  width: 8px;
  height: 8px;
  background: var(--green-primary);
  flex-shrink: 0;
}

.username,
.username-mobile {
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.logout-btn {
  background: none;
  border: 1px solid var(--border-card);
  color: var(--text-secondary);
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-body);
  flex-shrink: 0;
}

.logout-btn:hover {
  border-color: var(--border-active);
  color: var(--text-primary);
  background: var(--green-glow);
}

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .header {
    padding: 0 12px;
  }

  .header-left {
    gap: 10px;
  }

  .sidebar-toggle,
  .mobile-menu-btn {
    width: 36px;
    height: 36px;
    font-size: 18px;
  }

  .page-title {
    font-size: 13px;
  }

  .logout-btn {
    padding: 4px 10px;
    font-size: 11px;
    min-height: 36px;
  }
}

@media (max-width: 480px) {
  .header {
    padding: 0 8px;
  }

  .header-left {
    gap: 8px;
  }

  .page-title {
    font-size: 11px;
  }

  .logout-btn {
    padding: 4px 8px;
    font-size: 10px;
  }
}
</style>
