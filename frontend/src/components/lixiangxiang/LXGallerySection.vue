<template>
  <section id="gallery" class="lx-section lx-gallery">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Gallery</p>
      <h2 class="lx-section-title">截图相册</h2>
      <p class="lx-section-desc">记录理想乡的每一帧光影 —— 点击图片可放大预览。</p>

      <div class="lx-gallery-tabs">
        <button
          class="lx-tab"
          :class="{ active: activeCat === 'all' }"
          @click="setCategory('all')"
        >全部 <span class="lx-tab-count">{{ images.length }}</span></button>
        <button
          v-for="c in categories"
          :key="c.id"
          class="lx-tab"
          :class="{ active: activeCat === c.id }"
          @click="setCategory(c.id)"
        >{{ c.name }} <span class="lx-tab-count">{{ c.image_count ?? 0 }}</span></button>
      </div>

      <div v-if="filteredImages.length === 0" class="lx-empty">该分类暂无图片</div>

      <div v-else class="lx-gallery-grid">
        <figure
          v-for="img in filteredImages"
          :key="img.id"
          class="lx-photo"
        >
          <el-image
            class="lx-photo-img"
            :src="img.image_path"
            :preview-src-list="filteredImages.map(x => x.image_path)"
            :initial-index="filteredImages.findIndex(x => x.id === img.id)"
            :preview-teleported="true"
            fit="cover"
            :alt="img.title"
            lazy
          >
            <template #error>
              <div class="lx-photo-error">图片加载失败</div>
            </template>
          </el-image>
          <figcaption class="lx-photo-caption">
            <span class="lx-photo-title">{{ img.title || '未命名' }}</span>
            <span v-if="img.description" class="lx-photo-desc">{{ img.description }}</span>
          </figcaption>
        </figure>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { LxCategory, LxImage } from '@/api/lixiangxiang'

const props = defineProps<{ categories: LxCategory[]; images: LxImage[] }>()

const activeCat = ref('all')

function setCategory(id: string) {
  activeCat.value = id
}

const filteredImages = computed(() => {
  if (activeCat.value === 'all') return props.images
  return props.images.filter(img => img.category_id === activeCat.value)
})
</script>

<style scoped>
.lx-section {
  padding: 96px 24px;
  background: var(--bg-page);
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
  margin: 0 0 40px;
}

/* ================= Tabs ================= */
.lx-gallery-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 36px;
}

.lx-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 18px;
  border-radius: 999px;
  border: 1px solid var(--border-default);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 14px;
  cursor: pointer;
  transition: all 150ms var(--ease-out);
}

.lx-tab:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.lx-tab.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #FFF8F2;
}

.lx-tab-count {
  font-family: var(--font-mono);
  font-size: 12px;
  opacity: 0.75;
}

.lx-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 60px 0;
  font-family: var(--font-sans);
}

/* ================= Grid ================= */
.lx-gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.lx-photo {
  margin: 0;
  border-radius: 14px;
  overflow: hidden;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  cursor: zoom-in;
  transition: transform 150ms var(--ease-out), box-shadow 150ms var(--ease-out), border-color 150ms var(--ease-out);
}

.lx-photo:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: var(--accent);
}

.lx-photo-img {
  width: 100%;
  aspect-ratio: 16 / 10;
  display: block;
}

.lx-photo-img :deep(img) {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 400ms var(--ease-out);
}

.lx-photo:hover .lx-photo-img :deep(img) {
  transform: scale(1.04);
}

.lx-photo-error {
  width: 100%;
  height: 100%;
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 13px;
  background: var(--bg-page);
}

.lx-photo-caption {
  padding: 12px 16px 14px;
}

.lx-photo-title {
  display: block;
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 3px;
}

.lx-photo-desc {
  display: block;
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ================= Responsive ================= */
@media (max-width: 768px) {
  .lx-section {
    padding: 64px 16px;
  }

  .lx-gallery-grid {
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 12px;
  }
}
</style>