<template>
  <div class="app-layout" :class="{ 'mobile-open': mobileDrawerOpen }">
    <!-- Desktop Sidebar -->
    <aside v-if="!isPublicGuest" class="app-sidebar desktop-only" :class="{ collapsed: isCollapsed }">
      <AppSidebar :collapsed="isCollapsed" @toggle="isCollapsed = !isCollapsed" />
    </aside>

    <!-- Mobile Drawer Overlay -->
    <Transition name="drawer-fade">
      <div v-if="mobileDrawerOpen" class="mobile-overlay" @click="mobileDrawerOpen = false" />
    </Transition>

    <!-- Mobile Drawer Sidebar -->
    <Transition name="drawer-slide">
      <aside v-if="mobileDrawerOpen && !isPublicGuest" class="app-sidebar mobile-drawer">
        <AppSidebar :collapsed="false" @toggle="mobileDrawerOpen = false" :is-mobile="true" />
      </aside>
    </Transition>

    <div class="app-body">
      <header v-if="!isPublicGuest" class="app-header">
        <AppHeader
          :is-mobile="true"
          @toggle-sidebar="isCollapsed = !isCollapsed"
          @open-mobile-menu="mobileDrawerOpen = true"
        />
      </header>
      <main class="app-main">
        <!-- keep-alive 缓存状态页与妙妙工具：切换路由不重新挂载/不重复拉大体积数据，
             解决"从其他页面进入卡顿"；BotStatusView 内部 watch engine 立即刷新 -->
        <router-view v-slot="{ Component }">
          <keep-alive :include="['BotStatusView', 'MiaomiaoView']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </main>
      <footer class="app-footer">
        <a
          href="https://beian.miit.gov.cn"
          target="_blank"
          rel="noopener noreferrer"
        >渝ICP备2026011793号-1</a>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'

const route = useRoute()
const authStore = useAuthStore()

/** 访客模式：未登录且当前路由标记为 public（如妙妙工具）时，
 *  隐藏侧边栏与头部，纯内容浏览；已登录用户（任意权限组）保留自己的侧边栏。 */
const isPublicGuest = computed(() => !authStore.isLoggedIn && route.meta.public === true)

const isCollapsed = ref(false)
const mobileDrawerOpen = ref(false)

/** 桌面宽度下强制关闭移动抽屉，避免「窗口拉宽后桌面栏+抽屉并存」出现两个侧边栏 */
function handleViewportChange() {
  if (window.matchMedia('(min-width: 769px)').matches) {
    mobileDrawerOpen.value = false
  }
}

onMounted(() => {
  window.addEventListener('resize', handleViewportChange)
  handleViewportChange()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleViewportChange)
})
</script>

<style scoped>
.app-layout {
  height: 100vh;
  height: 100dvh; /* dynamic viewport height for mobile browsers */
  display: flex;
  background: #000;
}

/* ---- Desktop Sidebar ---- */
.app-sidebar {
  width: 220px;
  flex-shrink: 0;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width 0.25s ease;
  z-index: 10;
}

.app-sidebar.collapsed {
  width: 60px;
}

/* ---- Mobile Drawer Sidebar ---- */
.mobile-drawer {
  display: none; /* 兜底：桌面宽度下即使状态残留也不显示，避免双侧边栏 */
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 260px !important;
  max-width: 80vw;
  z-index: 200;
  box-shadow: 4px 0 20px rgba(0, 0, 0, 0.6);
}

/* ---- Mobile Overlay ---- */
.mobile-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 150;
}

/* ---- Drawer Transitions ---- */
.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.25s ease;
}
.drawer-fade-enter-from,
.drawer-fade-leave-to {
  opacity: 0;
}

.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition: transform 0.25s ease;
}
.drawer-slide-enter-from,
.drawer-slide-leave-to {
  transform: translateX(-100%);
}

/* ---- App Body ---- */
.app-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0; /* prevent flex blowout */
}

.app-header {
  height: 56px;
  flex-shrink: 0;
}

.app-main {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px 28px;
  background: #000;
  -webkit-overflow-scrolling: touch;
}

.app-footer {
  flex-shrink: 0;
  text-align: center;
  padding: 10px 16px 12px;
  background: #000;
}

.app-footer a {
  color: #666;
  font-size: 12px;
  text-decoration: none;
  transition: color 0.2s;
}

.app-footer a:hover {
  color: #999;
}

/* ============ TABLET: auto-collapse sidebar ============ */
@media (max-width: 1024px) {
  .desktop-only.app-sidebar {
    width: 60px;
  }
  .app-main {
    padding: 20px 16px;
  }
}

/* ============ MOBILE: hide sidebar, enable drawer ============ */
@media (max-width: 768px) {
  .desktop-only {
    display: none !important;
  }

  .mobile-drawer {
    display: block; /* 覆盖上面的 display:none 兜底，小屏才显示抽屉 */
  }

  .app-header {
    height: 52px;
  }

  .app-main {
    padding: 16px 12px;
    padding-bottom: calc(16px + var(--safe-area-bottom));
  }
}

/* Small phone tweaks */
@media (max-width: 480px) {
  .app-main {
    padding: 12px 8px;
    padding-bottom: calc(12px + var(--safe-area-bottom));
  }
}
</style>
