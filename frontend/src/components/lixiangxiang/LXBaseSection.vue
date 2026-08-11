<template>
  <section id="bases" ref="rootRef" class="lx-section lx-bases" :class="{ 'is-revealed': revealed }">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Bases · 地图基地</p>
      <h2 class="lx-section-title">四座家园 · 领地测绘</h2>
      <p class="lx-section-desc">主城、望岳与星野——每一座基地都有精确的坐标与故事。</p>

      <div v-if="bases.length === 0" class="lx-empty">基地资料整理中…</div>

      <div class="lx-base-list">
        <article v-for="(b, i) in bases" :key="b.id" class="lx-base-card" :class="{ reverse: i % 2 === 1 }">
          <div class="lx-base-media">
            <img v-if="b.image_path" :src="b.image_path" :alt="b.name" loading="lazy" />
            <div v-else class="lx-base-placeholder">基地建设中</div>
          </div>
          <div class="lx-base-body">
            <div class="lx-base-head">
              <span class="lx-base-index">测绘记录 · {{ String(i + 1).padStart(2, '0') }}</span>
              <span v-if="b.coordinates" class="lx-base-coords-badge">
                <i class="lx-pin-mini"></i>{{ coordText(b.coordinates) }}
              </span>
            </div>
            <h3 class="lx-base-name">{{ b.name }}</h3>
            <p class="lx-base-desc">{{ b.description }}</p>
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

/** 坐标解析："-2673, 57, 9627" → "X: -2673 · Z: 9627"（测绘坐标牌） */
function coordText(raw: string): string {
  const parts = raw.split(',').map(s => s.trim()).filter(Boolean)
  if (parts.length >= 3) return `X: ${parts[0]} · Z: ${parts[2]}`
  return raw
}
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

.lx-base-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

/* 测绘记录标签（编号成为"记录序列"语义） */
.lx-base-index {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 2px;
  color: var(--lx-blue);
  text-transform: uppercase;
}

/* 坐标徽章（图钉标记） */
.lx-base-coords-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 6px;
  background: var(--accent-soft);
  border: 1px dashed var(--accent-ring);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
  letter-spacing: 0.5px;
}

.lx-pin-mini {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--lx-pin);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lx-pin) 22%, transparent);
  flex-shrink: 0;
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
  margin: 0;
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