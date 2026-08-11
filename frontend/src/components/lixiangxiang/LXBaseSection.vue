<template>
  <section id="bases" ref="rootRef" class="lx-section lx-bases" :class="{ 'is-revealed': revealed }">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Bases · 地图基地</p>
      <h2 class="lx-section-title">我们的四座家园</h2>
      <p class="lx-section-desc">每一座基地，都是一段从零开始的故事。</p>

      <div v-if="bases.length === 0" class="lx-empty">基地资料整理中…</div>

      <div class="lx-base-list">
        <article v-for="(b, i) in bases" :key="b.id" class="lx-base-card" :class="{ reverse: i % 2 === 1 }">
          <div class="lx-base-media">
            <img v-if="b.image_path" :src="b.image_path" :alt="b.name" loading="lazy" />
            <div v-else class="lx-base-placeholder">基地建设中</div>
          </div>
          <div class="lx-base-body">
            <span class="lx-base-index">{{ String(i + 1).padStart(2, '0') }}</span>
            <h3 class="lx-base-name">{{ b.name }}</h3>
            <p class="lx-base-desc">{{ b.description }}</p>
            <div v-if="b.coordinates" class="lx-base-coords">
              <span class="lx-coords-label">坐标</span>
              <span class="lx-coords-value">{{ b.coordinates }}</span>
            </div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { LxBase } from '@/api/lixiangxiang'
import { useReveal } from '@/composables/useReveal'

defineProps<{ bases: LxBase[] }>()

const { rootRef, revealed } = useReveal()
</script>

<style scoped>
.lx-section {
  padding: 110px 24px 120px;
  background: var(--bg-page);
  border-top: 1px solid var(--border-subtle);
  opacity: 0;
  transform: translateY(24px);
  transition: opacity 0.7s var(--ease-out), transform 0.7s var(--ease-out);
}

.lx-section.is-revealed {
  opacity: 1;
  transform: none;
}

.lx-section-inner {
  max-width: 1120px;
  margin: 0 auto;
}

.lx-eyebrow {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 4px;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 14px;
}

.lx-section-title {
  font-family: var(--font-display);
  font-size: clamp(30px, 4.2vw, 46px);
  font-weight: 400;
  color: var(--text-primary);
  margin: 0 0 12px;
  letter-spacing: 2px;
  line-height: 1.25;
}

.lx-section-desc {
  font-family: var(--font-sans);
  font-size: 15px;
  color: var(--text-muted);
  margin: 0 0 56px;
  letter-spacing: 0.5px;
}

.lx-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 60px 0;
  font-family: var(--font-sans);
}

/* ================= 全宽大图卡片 ================= */
.lx-base-list {
  display: flex;
  flex-direction: column;
  gap: 56px;
}

.lx-base-card {
  position: relative;
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 44px;
  align-items: center;
}

.lx-base-card.reverse {
  grid-template-columns: 1fr 1.55fr;
}

.lx-base-card.reverse .lx-base-media {
  order: 2;
}

.lx-base-media {
  position: relative;
  border-radius: 16px;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
}

.lx-base-media::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 16px;
  border: 1px solid var(--border-subtle);
  pointer-events: none;
}

.lx-base-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 600ms var(--ease-out);
}

.lx-base-card:hover .lx-base-media img {
  transform: scale(1.045);
}

.lx-base-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 14px;
}

.lx-base-body {
  position: relative;
  padding: 16px 4px;
}

/* 超大衬线序号（背景式） */
.lx-base-index {
  font-family: var(--font-display);
  font-size: 64px;
  line-height: 1;
  color: transparent;
  -webkit-text-stroke: 1px var(--border-strong);
  display: block;
  margin-bottom: 18px;
  transition: color 300ms var(--ease-out), -webkit-text-stroke-color 300ms var(--ease-out);
}

.lx-base-card:hover .lx-base-index {
  color: var(--accent-soft);
  -webkit-text-stroke-color: var(--accent);
}

.lx-base-name {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 400;
  color: var(--text-primary);
  margin: 0 0 16px;
  letter-spacing: 1px;
}

.lx-base-desc {
  font-family: var(--font-body);
  font-size: 15.5px;
  line-height: 2;
  color: var(--text-secondary);
  margin: 0 0 24px;
}

.lx-base-coords {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 7px 14px;
  border-radius: 7px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-ring);
}

.lx-coords-label {
  font-family: var(--font-sans);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--accent);
}

.lx-coords-value {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-secondary);
}

/* ================= Responsive ================= */
@media (max-width: 900px) {
  .lx-base-card,
  .lx-base-card.reverse {
    grid-template-columns: 1fr;
    gap: 28px;
  }

  .lx-base-card.reverse .lx-base-media {
    order: 0;
  }

  .lx-base-index {
    font-size: 52px;
  }
}

@media (max-width: 768px) {
  .lx-section {
    padding: 72px 16px 88px;
  }

  .lx-base-list {
    gap: 44px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lx-section {
    opacity: 1;
    transform: none;
    transition: none;
  }

  .lx-base-media img { transition: none; }
}
</style>