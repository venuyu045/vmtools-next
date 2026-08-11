<template>
  <header class="lx-header">
    <div class="lx-header-inner">
      <a class="lx-logo" href="#top" @click.prevent="scrollToTop">
        <span class="lx-logo-mark">理</span>
        <span class="lx-logo-text">理想乡</span>
      </a>

      <nav class="lx-nav" :class="{ open: menuOpen }">
        <a v-for="item in navItems" :key="item.href" class="lx-nav-link" :href="item.href" @click="closeMenu">
          {{ item.label }}
        </a>
      </nav>

      <div class="lx-header-actions">
        <router-link to="/dashboard" class="lx-console-btn" title="进入控制台">
          控制台
          <span class="lx-arrow">→</span>
        </router-link>
        <button class="lx-menu-btn" :aria-expanded="menuOpen" aria-label="打开菜单" @click="menuOpen = !menuOpen">
          <span v-if="!menuOpen">☰</span>
          <span v-else>✕</span>
        </button>
      </div>
    </div>
  </header>

  <section id="top" class="lx-hero">
    <div class="lx-hero-inner">
      <p class="lx-hero-eyebrow">Minecraft 生存服务器 · 2023 年至今</p>
      <h1 class="lx-hero-title">理想乡</h1>
      <p class="lx-hero-slogan">{{ slogan || '方块之间，是家与远方' }}</p>
      <p class="lx-hero-sub">
        一座由 22 位玩家共同筑造的生存之城 —— 共建、共居、共享。
      </p>
      <div class="lx-hero-cta">
        <a class="lx-cta-primary" href="#intro">了解我们</a>
        <a class="lx-cta-ghost" href="#gallery">浏览相册</a>
      </div>
    </div>
    <div class="lx-hero-glow" aria-hidden="true"></div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { lxPublicApi } from '@/api/lixiangxiang'

const navItems = [
  { href: '#intro', label: '组织介绍' },
  { href: '#members', label: '成员' },
  { href: '#bases', label: '地图基地' },
  { href: '#gallery', label: '相册' },
]

const menuOpen = ref(false)
const slogan = ref('')

function closeMenu() {
  menuOpen.value = false
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(async () => {
  try {
    const { data } = await lxPublicApi.info()
    slogan.value = data.slogan
  } catch {
    /* 加载失败时使用默认标语 */
  }
})
</script>

<style scoped>
/* ================= Header ================= */
.lx-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: color-mix(in srgb, var(--bg-page) 88%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border-subtle);
}

.lx-header-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.lx-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  flex-shrink: 0;
}

.lx-logo-mark {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--accent), #B85C38);
  color: #FFF8F2;
  font-family: var(--font-display);
  font-size: 17px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px var(--accent-ring);
}

.lx-logo-text {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.lx-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  justify-content: center;
}

.lx-nav-link {
  padding: 8px 14px;
  border-radius: 8px;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: color 150ms var(--ease-out), background-color 150ms var(--ease-out);
}

.lx-nav-link:hover {
  color: var(--accent);
  background: var(--bg-hover);
}

.lx-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.lx-console-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  background: var(--accent);
  color: #FFF8F2;
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: background-color 150ms var(--ease-out), transform 150ms var(--ease-out);
}

.lx-console-btn:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
}

.lx-arrow {
  transition: transform 150ms var(--ease-out);
}

.lx-console-btn:hover .lx-arrow {
  transform: translateX(3px);
}

.lx-menu-btn {
  display: none;
  width: 40px;
  height: 40px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: 18px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
}

/* ================= Hero ================= */
.lx-hero {
  position: relative;
  overflow: hidden;
  background: var(--bg-page);
}

.lx-hero-inner {
  position: relative;
  z-index: 1;
  max-width: 1120px;
  margin: 0 auto;
  padding: 120px 24px 130px;
  text-align: center;
}

.lx-hero-eyebrow {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 18px;
}

.lx-hero-title {
  font-family: var(--font-display);
  font-size: clamp(56px, 9vw, 96px);
  font-weight: 400;
  line-height: 1.05;
  color: var(--text-primary);
  margin: 0 0 16px;
  letter-spacing: 4px;
}

.lx-hero-slogan {
  font-family: var(--font-body);
  font-size: clamp(18px, 2.6vw, 26px);
  color: var(--text-secondary);
  margin: 0 0 20px;
  font-style: italic;
}

.lx-hero-sub {
  font-family: var(--font-sans);
  font-size: 15px;
  color: var(--text-muted);
  margin: 0 0 40px;
  max-width: 560px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.7;
}

.lx-hero-cta {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}

.lx-cta-primary {
  display: inline-flex;
  align-items: center;
  padding: 12px 28px;
  border-radius: 10px;
  background: var(--accent);
  color: #FFF8F2;
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  transition: background-color 150ms var(--ease-out), transform 150ms var(--ease-out);
}

.lx-cta-primary:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
}

.lx-cta-ghost {
  display: inline-flex;
  align-items: center;
  padding: 12px 28px;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 500;
  text-decoration: none;
  transition: border-color 150ms var(--ease-out), background-color 150ms var(--ease-out);
}

.lx-cta-ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}

/* 暖橙渐变光晕装饰 */
.lx-hero-glow {
  position: absolute;
  top: -120px;
  left: 50%;
  transform: translateX(-50%);
  width: 720px;
  height: 420px;
  background:
    radial-gradient(ellipse at center, var(--accent-ring), transparent 65%),
    radial-gradient(ellipse at 30% 40%, rgba(217, 119, 87, 0.08), transparent 60%);
  filter: blur(30px);
  pointer-events: none;
}

/* ================= Responsive ================= */
@media (max-width: 768px) {
  .lx-header-inner {
    height: 56px;
    padding: 0 16px;
  }

  .lx-nav {
    position: fixed;
    top: 56px;
    left: 0;
    right: 0;
    flex-direction: column;
    align-items: stretch;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border-subtle);
    box-shadow: var(--shadow-md);
    padding: 8px 12px 16px;
    display: none;
    z-index: 99;
  }

  .lx-nav.open {
    display: flex;
  }

  .lx-nav-link {
    padding: 13px 14px;
    font-size: 15px;
    border-radius: 8px;
  }

  .lx-menu-btn {
    display: flex;
  }

  .lx-console-btn {
    padding: 7px 13px;
    font-size: 13px;
  }

  .lx-hero-inner {
    padding: 88px 20px 96px;
  }
}
</style>