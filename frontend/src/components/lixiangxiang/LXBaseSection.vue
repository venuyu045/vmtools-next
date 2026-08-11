<template>
  <section id="bases" class="lx-section lx-bases">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Bases</p>
      <h2 class="lx-section-title">地图基地</h2>
      <p class="lx-section-desc">我们的家园分布在主世界的各个角落 —— 每一座基地都有一段故事。</p>

      <div v-if="bases.length === 0" class="lx-empty">基地资料整理中…</div>

      <div class="lx-base-list">
        <article v-for="(b, i) in bases" :key="b.id" class="lx-base-card" :class="{ reverse: i % 2 === 1 }">
          <div class="lx-base-media">
            <img v-if="b.image_path" :src="b.image_path" :alt="b.name" loading="lazy" />
            <div v-else class="lx-base-placeholder">基地建设中</div>
          </div>
          <div class="lx-base-body">
            <span class="lx-base-index">0{{ i + 1 }}</span>
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

defineProps<{ bases: LxBase[] }>()
</script>

<style scoped>
.lx-section {
  padding: 96px 24px;
  background: var(--bg-card);
  border-top: 1px solid var(--border-subtle);
}

.lx-section-inner {
  max-width: 1120px;
  margin: 0 auto;
}

.lx-eyebrow {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 10px;
}

.lx-section-title {
  font-family: var(--font-display);
  font-size: clamp(30px, 4vw, 44px);
  font-weight: 400;
  color: var(--text-primary);
  margin: 0 0 12px;
  letter-spacing: 1px;
}

.lx-section-desc {
  font-family: var(--font-sans);
  font-size: 15px;
  color: var(--text-muted);
  margin: 0 0 48px;
}

.lx-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 60px 0;
  font-family: var(--font-sans);
}

/* ================= Base Cards ================= */
.lx-base-list {
  display: flex;
  flex-direction: column;
  gap: 40px;
}

.lx-base-card {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 40px;
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  padding: 28px;
  transition: transform 150ms var(--ease-out), box-shadow 150ms var(--ease-out), border-color 150ms var(--ease-out);
}

.lx-base-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: var(--accent);
}

.lx-base-card.reverse {
  grid-template-columns: 1fr 1.2fr;
}

.lx-base-card.reverse .lx-base-media {
  order: 2;
}

.lx-base-media {
  border-radius: 14px;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
}

.lx-base-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 400ms var(--ease-out);
}

.lx-base-card:hover .lx-base-media img {
  transform: scale(1.03);
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
  padding: 12px 8px;
}

.lx-base-index {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--accent);
  letter-spacing: 2px;
}

.lx-base-name {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 400;
  color: var(--text-primary);
  margin: 10px 0 14px;
}

.lx-base-desc {
  font-family: var(--font-body);
  font-size: 15.5px;
  line-height: 1.9;
  color: var(--text-secondary);
  margin: 0 0 20px;
}

.lx-base-coords {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: 8px;
  background: var(--accent-soft);
}

.lx-coords-label {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
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
    gap: 24px;
  }

  .lx-base-card.reverse .lx-base-media {
    order: 0;
  }
}

@media (max-width: 768px) {
  .lx-section {
    padding: 64px 16px;
  }

  .lx-base-card {
    padding: 18px;
  }
}
</style>