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
    <div class="lx-hero-grid">
      <div class="lx-hero-main">
        <p class="lx-hero-eyebrow">Minecraft 玩家组织 · 二〇二三年至今</p>
        <h1 class="lx-hero-title">理想乡</h1>
        <p class="lx-hero-slogan">{{ slogan || '方块之间，是家与远方' }}</p>
        <p class="lx-hero-sub">
          一个由 22 位玩家共同经营的 Minecraft 玩家组织。自 2023 年初春成立至今，
          成员们建起了四座基地、跨世界铁路与无数座亲手搭起的房子——
          这里的一切，都来自每一位成员的付出。
        </p>
        <div class="lx-hero-cta">
          <a class="lx-cta-primary" href="#intro">了解我们</a>
          <a class="lx-cta-ghost" href="#gallery">浏览相册</a>
        </div>
      </div>

      <div class="lx-hero-side" aria-hidden="true">
        <div class="lx-pin-card lx-pin-1">
          <span class="lx-pin-dot"></span>
          <span class="lx-pin-value">2023</span>
          <span class="lx-pin-label">建服 · 初春</span>
        </div>
        <div class="lx-pin-card lx-pin-2">
          <span class="lx-pin-dot"></span>
          <span class="lx-pin-value">{{ memberCount ?? 22 }}</span>
          <span class="lx-pin-label">位成员</span>
        </div>
        <div class="lx-pin-card lx-pin-3">
          <span class="lx-pin-dot"></span>
          <span class="lx-pin-value">4</span>
          <span class="lx-pin-label">座基地</span>
        </div>
        <div class="lx-seal-caption">
          <span class="lx-seal-caption-zh">理想乡 · 领地测绘</span>
          <span class="lx-seal-caption-en">LIXIANGXIANG EST. 2023 · X:-2673 Z:9627</span>
        </div>
      </div>
    </div>
    <div class="lx-hero-glow" aria-hidden="true"></div>
    <div class="lx-hero-rule" aria-hidden="true"></div>
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

/** 成员数（Home 传入，缺省 22）——用于 Hero 图钉数据牌 */
defineProps<{ memberCount?: number }>()

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
    /* 使用默认标语 */
  }
})
</script>

<style scoped>
/* ================= Header ================= */
.lx-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: color-mix(in srgb, var(--bg-page) 86%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
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
  border-bottom: 1px dashed var(--border-default);
}

.lx-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  flex-shrink: 0;
}

.lx-logo-mark {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: var(--text-primary);
  color: var(--bg-page);
  font-family: var(--font-display);
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0;
}

.lx-logo-text {
  font-family: var(--font-display);
  font-size: 19px;
  color: var(--text-primary);
  letter-spacing: 2px;
}

.lx-nav {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  justify-content: center;
}

.lx-nav-link {
  position: relative;
  padding: 10px 14px;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 14px;
  letter-spacing: 0.4px;
  text-decoration: none;
  transition: color 200ms var(--ease-out);
}

.lx-nav-link::after {
  content: '';
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 4px;
  height: 1px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 250ms var(--ease-out);
}

.lx-nav-link:hover {
  color: var(--text-primary);
}

.lx-nav-link:hover::after {
  transform: scaleX(1);
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
  border-radius: 7px;
  border: 1px solid var(--text-primary);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-decoration: none;
  background: transparent;
  transition: background-color 200ms var(--ease-out), color 200ms var(--ease-out), transform 200ms var(--ease-out);
}

.lx-console-btn:hover {
  background: var(--text-primary);
  color: var(--bg-page);
  transform: translateY(-1px);
}

.lx-arrow {
  transition: transform 200ms var(--ease-out);
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
  font-size: 17px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
}

/* ================= Hero（杂志式左对齐） ================= */
.lx-hero {
  position: relative;
  overflow: hidden;
  background: var(--bg-page);
}

.lx-hero-grid {
  position: relative;
  z-index: 1;
  max-width: 1120px;
  margin: 0 auto;
  padding: 110px 24px 120px;
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 64px;
  align-items: center;
}

.lx-hero-eyebrow {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--accent);
  margin: 0 0 22px;
}

.lx-hero-title {
  font-family: var(--font-display);
  font-size: clamp(64px, 9vw, 108px);
  font-weight: 400;
  line-height: 1;
  color: var(--text-primary);
  margin: 0 0 14px;
  letter-spacing: 6px;
  text-indent: 6px; /* 视觉居中补偿字距 */
}

.lx-hero-slogan {
  font-family: var(--font-body);
  font-size: clamp(17px, 2.2vw, 22px);
  font-style: italic;
  color: var(--text-secondary);
  margin: 0 0 22px;
  letter-spacing: 1px;
}

.lx-hero-sub {
  max-width: 520px;
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 2;
  color: var(--text-muted);
  margin: 0 0 40px;
}

.lx-hero-cta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.lx-cta-primary {
  display: inline-flex;
  align-items: center;
  padding: 12px 26px;
  border-radius: 7px;
  background: var(--accent);
  color: #FFF8F2;
  font-family: var(--font-sans);
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-decoration: none;
  transition: background-color 200ms var(--ease-out), transform 200ms var(--ease-out), box-shadow 200ms var(--ease-out);
}

.lx-cta-primary:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px var(--accent-ring);
}

.lx-cta-ghost {
  display: inline-flex;
  align-items: center;
  padding: 12px 26px;
  border-radius: 7px;
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 14.5px;
  font-weight: 500;
  text-decoration: none;
  transition: border-color 200ms var(--ease-out), color 200ms var(--ease-out);
}

.lx-cta-ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* ---- 右侧图钉数据牌（领地测绘语言） ---- */
.lx-hero-side {
  position: relative;
  min-height: 340px;
}

.lx-pin-card {
  position: absolute;
  width: 150px;
  padding: 16px 18px 14px;
  border-radius: 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-md);
  transition: transform 300ms var(--ease-out), border-color 300ms var(--ease-out);
}

.lx-pin-1 { top: 6px; left: 0; }
.lx-pin-2 { top: 128px; left: 118px; }
.lx-pin-3 { top: 6px; left: 236px; }

.lx-pin-card:hover {
  border-color: var(--lx-pin);
}

.lx-hero-side:hover .lx-pin-1 { transform: translateY(-6px) rotate(-1deg); }
.lx-hero-side:hover .lx-pin-2 { transform: translateY(-4px) rotate(1deg); }
.lx-hero-side:hover .lx-pin-3 { transform: translateY(-7px) rotate(-0.5deg); }

.lx-pin-dot {
  display: block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--lx-pin);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lx-pin) 25%, transparent);
  margin-bottom: 10px;
}

.lx-pin-value {
  display: block;
  font-family: var(--font-display);
  font-size: 30px;
  line-height: 1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  margin-bottom: 5px;
}

.lx-pin-label {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 1.5px;
  color: var(--text-muted);
}

.lx-seal-caption {
  position: absolute;
  bottom: 4px;
  left: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.lx-seal-caption-zh {
  font-family: var(--font-body);
  font-size: 14px;
  letter-spacing: 3px;
  color: var(--text-primary);
}

.lx-seal-caption-en {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 2px;
  color: var(--text-muted);
}

/* ---- 背景装饰 ---- */
.lx-hero-glow {
  position: absolute;
  top: -160px;
  right: -120px;
  width: 620px;
  height: 520px;
  background: radial-gradient(ellipse at center, var(--accent-ring), transparent 62%);
  filter: blur(40px);
  pointer-events: none;
}

.lx-hero-rule {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  border-bottom: 1px dashed var(--border-default);
}

/* ================= Responsive ================= */
@media (max-width: 900px) {
  .lx-hero-grid {
    grid-template-columns: 1fr;
    gap: 40px;
    padding: 88px 24px 96px;
  }

  .lx-hero-side {
    display: none;
  }
}

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
  }

  .lx-nav-link::after {
    display: none;
  }

  .lx-menu-btn {
    display: flex;
  }

  .lx-console-btn {
    padding: 7px 13px;
    font-size: 13px;
  }

  .lx-hero-grid {
    padding: 72px 20px 80px;
  }

  .lx-hero-title {
    letter-spacing: 4px;
    text-indent: 4px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lx-pin-card { transition: none; }
  .lx-arrow, .lx-console-btn, .lx-cta-primary, .lx-cta-ghost { transition: none; }
}
</style>