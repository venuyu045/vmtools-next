<template>
  <div class="app-layout" :class="{ 'mobile-open': mobileDrawerOpen }">
    <!-- Desktop Sidebar（访客也显示：未登录 roleRank=guest，侧边栏自动只显示总览+工具） -->
    <aside class="app-sidebar desktop-only" :class="{ collapsed: sidebarCollapsed }">
      <!-- 时装中心是独立子应用：进入后侧边栏只保留时装内容（商店/衣柜/管理） -->
      <FashionSidebar
        v-if="isFashionCenter"
        :collapsed="sidebarCollapsed"
        @toggle="toggleSidebar"
      />
      <AppSidebar v-else :collapsed="sidebarCollapsed" @toggle="toggleSidebar" />
    </aside>

    <!-- Mobile Drawer Overlay -->
    <Transition name="drawer-fade">
      <div v-if="mobileDrawerOpen" class="mobile-overlay" @click="mobileDrawerOpen = false" />
    </Transition>

    <!-- Mobile Drawer Sidebar -->
    <Transition name="drawer-slide">
      <aside v-if="mobileDrawerOpen" ref="mobileDrawerRef" tabindex="-1" class="app-sidebar mobile-drawer">
        <FashionSidebar
          v-if="isFashionCenter"
          :collapsed="false"
          @toggle="mobileDrawerOpen = false"
          :is-mobile="true"
        />
        <AppSidebar
          v-else
          :collapsed="false"
          @toggle="mobileDrawerOpen = false"
          :is-mobile="true"
        />
      </aside>
    </Transition>

    <div class="app-body">
      <header class="app-header">
        <AppHeader
          @toggle-sidebar="toggleSidebar"
          @open-mobile-menu="openMobileMenu"
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'
import FashionSidebar from './FashionSidebar.vue'
import AppHeader from './AppHeader.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

/**
 * 是否处于「时装中心」子应用。
 *
 * 时装中心（/fashion/*）的侧边栏只保留时装内容（时装商店 / 我的衣柜 / 时装管理），
 * 主站侧边栏里的时装入口已全部移除 —— 由路由 meta.fashionCenter 标记，
 * 新增时装相关页面时记得同样打上该 meta，否则会退回主站侧边栏。
 */
const isFashionCenter = computed(() => route.meta.fashionCenter === true)

/** 访客模式：未登录（且不在登录/注册页）。访客同样显示侧边栏（总览+工具只读）与头部，
 *  但内容区任何交互都会跳转登录页（只读浏览）。 */
const isGuestMode = computed(() => !authStore.isLoggedIn && route.path !== '/login' && route.path !== '/register')

/** 内容区容器（用于访客交互拦截；侧边栏/头部不在此容器内，导航与登录不受影响） */
const mainRef = ref<HTMLElement | null>(null)

/**
 * 该路由是否允许访客**自由交互**（不受只读拦截）。
 *
 * ⚠️ 2026-10-20 审查修复（中等·交互缺陷）：
 *   路由表里 `/miaomiao`（妙妙工具）标注 `meta.public = true`，注释明确写着
 *   「访客无需登录即可访问」，侧边栏也把它列在访客可展开的「工具」组里。
 *   但本组件的访客拦截器此前只排除 /login、/register 两条路径，
 *   于是**所有** click/change/input/keydown 都被 preventDefault 并跳登录页 →
 *   访客在妙妙工具页无法切标签、无法搜索、无法排序、无法翻页，
 *   页面实际上完全不可用（只剩静态首屏）。
 *   修复：`meta.public === true` 的路由放行交互；其余只读页（guestReadable）
 *   保持原有「交互即跳登录」的行为不变。
 */
function guestInteractionAllowed(): boolean {
  return route.meta.public === true
}

/** 访客模式拦截：内容区任何交互（点击/输入/回车/提交）→ 跳登录页并提示「前面的区域以后再来探索吧」 */
function onGuestInteract(e: Event) {
  if (authStore.isLoggedIn) return
  if (route.path === '/login' || route.path === '/register') return
  if (guestInteractionAllowed()) return
  e.preventDefault()
  e.stopPropagation()
  router.push({ path: '/login', query: { reason: 'locked' } })
}

/** ⚠️ 2026-10-19 审查修复（中等·可访问性）：
 *  原实现把 'keydown' 一并纳入拦截，导致访客在内容区按【任意键】——
 *  包括方向键、PageUp/PageDown、Home/End、空格（滚动）、Tab（焦点切换）、
 *  Esc —— 都会被 preventDefault 并跳登录页。结果是访客**完全无法用键盘滚动
 *  或浏览**，对键盘/读屏用户等同页面不可用（WCAG 2.1.1 键盘可达性失败）。
 *  改为：仅当按键发生在可编辑控件内，或按下 Enter/空格 这类「提交语义」键时才拦截。
 */
function onGuestKeydown(e: Event) {
  if (authStore.isLoggedIn) return
  if (route.path === '/login' || route.path === '/register') return
  if (guestInteractionAllowed()) return
  const ke = e as KeyboardEvent
  const target = ke.target as HTMLElement | null
  // 可编辑控件内的输入：视为交互意图，拦截
  const tag = (target?.tagName || '').toLowerCase()
  const editable = tag === 'input' || tag === 'textarea' || tag === 'select'
    || (target?.isContentEditable ?? false)
  // Enter / 空格：提交语义
  const submitKey = ke.key === 'Enter' || ke.key === ' '
  if (!editable && !submitKey) return   // 方向键/翻页/Tab/Esc 等一律放行
  ke.preventDefault()
  ke.stopPropagation()
  router.push({ path: '/login', query: { reason: 'locked' } })
}

const GUEST_INTERACT_EVENTS = ['click', 'change', 'input', 'submit'] as const

onMounted(() => {
  const el = mainRef.value
  if (el) {
    for (const evt of GUEST_INTERACT_EVENTS) {
      el.addEventListener(evt, onGuestInteract, true)
    }
    el.addEventListener('keydown', onGuestKeydown, true)
  }
})

onBeforeUnmount(() => {
  const el = mainRef.value
  if (el) {
    for (const evt of GUEST_INTERACT_EVENTS) {
      el.removeEventListener(evt, onGuestInteract, true)
    }
    el.removeEventListener('keydown', onGuestKeydown, true)
  }
})

/** 桌面侧边栏折叠状态：localStorage 持久化，刷新/重进不丢失 */
const COLLAPSE_STATE_KEY = 'vmtools-sidebar-collapsed'
const isCollapsed = ref(localStorage.getItem(COLLAPSE_STATE_KEY) === '1')
const mobileDrawerOpen = ref(false)

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value
  try {
    localStorage.setItem(COLLAPSE_STATE_KEY, isCollapsed.value ? '1' : '0')
  } catch { /* 忽略（隐私模式等） */ }
}

/** 抽屉可用区间：≤768px（手机竖屏）或 高度≤480px 的横屏手机（与 CSS 断点保持一致）。
 *  桌面端抽屉 display:none，若误触发只剩灰遮罩，故必须前置判定。 */
function isDrawerLayout() {
  return window.matchMedia('(max-width: 768px)').matches
    || (window.matchMedia('(max-height: 480px)').matches && window.matchMedia('(max-width: 1024px)').matches)
}

/** 打开移动抽屉 */
function openMobileMenu() {
  if (isDrawerLayout()) {
    mobileDrawerOpen.value = true
  }
}

/**
 * 平板（769–1024px）：global.css 媒体查询强制桌面侧边栏 60px 宽，
 * 但 CSS 无法同步组件内部折叠态 → 需 JS 联动，否则展开态内容（logo/分组标题/标签）溢出被裁剪。
 * sidebarCollapsed = 用户手动折叠 || 平板区间自动折叠。
 */
const isTabletAutoCollapsed = ref(false)
const sidebarCollapsed = computed(() => isCollapsed.value || isTabletAutoCollapsed.value)

/** 移动抽屉：打开时锁定 body 滚动（防背景滚动穿透）+ 焦点管理（聚焦抽屉/关闭还原） */
const mobileDrawerRef = ref<HTMLElement | null>(null)
let lastFocused: HTMLElement | null = null

watch(mobileDrawerOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
  if (open) {
    lastFocused = document.activeElement as HTMLElement | null
    // 等 Transition 挂载完成后再聚焦抽屉容器
    requestAnimationFrame(() => {
      mobileDrawerRef.value?.focus()
    })
  } else if (lastFocused) {
    // 关闭后焦点还原到触发元素（汉堡按钮）
    lastFocused.focus()
    lastFocused = null
  }
})

/** 抽屉键盘：ESC 关闭 + Tab 循环（focus trap，焦点不逃逸到背景内容） */
function onDrawerKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && mobileDrawerOpen.value) {
    mobileDrawerOpen.value = false
    return
  }
  if (e.key === 'Tab' && mobileDrawerOpen.value) {
    const drawer = mobileDrawerRef.value
    if (!drawer) return
    const focusables = drawer.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    if (focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }
}

/** 桌面宽度下强制关闭移动抽屉，避免「窗口拉宽后桌面栏+抽屉并存」出现两个侧边栏 */
function handleViewportChange() {
  if (window.matchMedia('(min-width: 769px)').matches) {
    mobileDrawerOpen.value = false
  }
  isTabletAutoCollapsed.value =
    window.matchMedia('(max-width: 1024px)').matches &&
    window.matchMedia('(min-width: 769px)').matches
}

onMounted(() => {
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('keydown', onDrawerKeydown)
  handleViewportChange()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('keydown', onDrawerKeydown)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.app-layout {
  height: 100vh;
  height: 100dvh; /* dynamic viewport height for mobile browsers */
  display: flex;
  background: var(--bg-page);
}

/* ---- Desktop Sidebar ---- */
.app-sidebar {
  width: 220px;
  flex-shrink: 0;
  overflow-y: auto;
  overflow-x: hidden;
  /* 折叠动画必须动 width（布局流依赖），缓动用统一曲线 */
  transition: width 250ms var(--ease-out);
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
  box-shadow: var(--shadow-lg);
  /* 刘海屏/手势条：抽屉内容避让左右与底部安全区 */
  padding-left: var(--safe-area-left);
  padding-bottom: var(--safe-area-bottom);
}

/* 抽屉容器聚焦由内部元素承担，容器本身不显示焦点环 */
.mobile-drawer:focus-visible {
  outline: none;
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
  background: var(--bg-page);
  -webkit-overflow-scrolling: touch;
}

.app-footer {
  flex-shrink: 0;
  text-align: center;
  padding: 10px 16px 12px;
  background: var(--bg-page);
}

.app-footer a {
  color: var(--text-muted);
  font-size: 12px;
  text-decoration: none;
  transition: color 0.2s;
}

.app-footer a:hover {
  color: var(--text-secondary);
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

/* ============ 手机横屏（高度极窄）：改用抽屉侧边栏 ============
   横屏手机宽度常为 780–930px，会命中上面的「平板自动折叠」规则，
   侧边栏被压成 60px 宽、只剩一排无文字的圆点，导航完全不可辨识；
   而横屏可用高度只有 360–430px，纵向空间本就紧张。
   此时与竖屏一致改用汉堡菜单 + 抽屉，把横向空间全部让给内容。 */
@media (max-height: 480px) and (max-width: 1024px) and (min-width: 769px) {
  .desktop-only {
    display: none !important;
  }
  .mobile-drawer {
    display: block;
  }
  /* 横屏顶栏压缩，给内容留高度 */
  .app-header {
    height: 44px;
  }
  .app-main {
    padding: 12px 14px;
    padding-bottom: calc(12px + var(--safe-area-bottom));
  }
  .app-footer {
    padding: 6px 16px;
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
    /* 刘海屏：顶栏内容下移，避免状态栏压住汉堡菜单/用户名 */
    padding-top: var(--safe-area-top);
    height: calc(52px + var(--safe-area-top));
  }

  .app-main {
    padding: 16px 12px;
    padding-bottom: calc(16px + var(--safe-area-bottom));
    /* 窄屏取消横向裁剪：内容超宽时允许滚动，而不是静默裁掉右侧内容
       （此前 overflow-x:hidden 会让宽表格/宽卡片右侧部分直接消失且无法触达） */
    overflow-x: auto;
    overscroll-behavior-x: contain;
  }

  /* 页脚备案号：贴底时避让手势条 */
  .app-footer {
    padding-bottom: calc(10px + var(--safe-area-bottom));
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
