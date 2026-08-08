<template>
  <div class="app-layout" :class="{ 'mobile-open': mobileDrawerOpen }">
    <!-- Desktop Sidebar（访客也显示：未登录 roleRank=guest，侧边栏自动只显示总览+工具） -->
    <aside class="app-sidebar desktop-only" :class="{ collapsed: isCollapsed }">
      <AppSidebar :collapsed="isCollapsed" @toggle="isCollapsed = !isCollapsed" />
    </aside>

    <!-- Mobile Drawer Overlay -->
    <Transition name="drawer-fade">
      <div v-if="mobileDrawerOpen" class="mobile-overlay" @click="mobileDrawerOpen = false" />
    </Transition>

    <!-- Mobile Drawer Sidebar -->
    <Transition name="drawer-slide">
      <aside v-if="mobileDrawerOpen" class="app-sidebar mobile-drawer">
        <AppSidebar :collapsed="false" @toggle="mobileDrawerOpen = false" :is-mobile="true" />
      </aside>
    </Transition>

    <div class="app-body">
      <header class="app-header">
        <AppHeader
          :is-mobile="true"
          @toggle-sidebar="isCollapsed = !isCollapsed"
          @open-mobile-menu="mobileDrawerOpen = true"
        />
      </header>
      <main ref="mainRef" class="app-main">
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
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

/** 访客模式：未登录（且不在登录/注册页）。访客同样显示侧边栏（总览+工具只读）与头部，
 *  但内容区任何交互都会跳转登录页（只读浏览）。 */
const isGuestMode = computed(() => !authStore.isLoggedIn && route.path !== '/login' && route.path !== '/register')

/** 内容区容器（用于访客交互拦截；侧边栏/头部不在此容器内，导航与登录不受影响） */
const mainRef = ref<HTMLElement | null>(null)

/** 访客模式拦截：内容区任何交互（点击/输入/回车/提交）→ 跳登录页 */
function onGuestInteract(e: Event) {
  if (authStore.isLoggedIn) return
  if (route.path === '/login' || route.path === '/register') return
  e.preventDefault()
  e.stopPropagation()
  router.push('/login')
}

const GUEST_INTERACT_EVENTS = ['click', 'change', 'input', 'keydown', 'submit'] as const

onMounted(() => {
  const el = mainRef.value
  if (el) {
    for (const evt of GUEST_INTERACT_EVENTS) {
      el.addEventListener(evt, onGuestInteract, true)
    }
  }
})

onBeforeUnmount(() => {
  const el = mainRef.value
  if (el) {
    for (const evt of GUEST_INTERACT_EVENTS) {
      el.removeEventListener(evt, onGuestInteract, true)
    }
  }
})

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
