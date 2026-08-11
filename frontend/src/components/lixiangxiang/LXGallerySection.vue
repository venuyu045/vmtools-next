<template>
  <section id="gallery" ref="rootRef" class="lx-section lx-gallery" :class="{ 'is-revealed': revealed }">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Gallery · 光影集</p>
      <h2 class="lx-section-title">光影集</h2>
      <p class="lx-section-desc">记录理想乡的每一帧光与影，点击图片可放大查看。</p>

      <div class="lx-gallery-tabs" role="tablist" aria-label="相册分类">
        <button
          class="lx-tab"
          :class="{ active: activeCat === 'all' }"
          @click="setCategory('all')"
        >全部<span class="lx-tab-count">{{ images.length }}</span></button>
        <button
          v-for="c in categories"
          :key="c.id"
          class="lx-tab"
          :class="{ active: activeCat === c.id }"
          @click="setCategory(c.id)"
        >{{ c.name }}<span class="lx-tab-count">{{ c.image_count ?? 0 }}</span></button>
      </div>

      <div v-if="filteredImages.length === 0" class="lx-empty">该分类暂无图片</div>

      <div v-else class="lx-masonry">
        <figure
          v-for="img in filteredImages"
          :key="img.id"
          class="lx-photo"
          @click="openPreview(img)"
        >
          <img
            :src="img.image_path"
            :alt="img.title"
            loading="lazy"
          />
          <figcaption class="lx-photo-caption">
            <span class="lx-photo-title">{{ img.title || '未命名' }}</span>
          </figcaption>
        </figure>
      </div>
    </div>

    <!-- 手写轻量灯箱 -->
    <Teleport to="body">
      <Transition name="lx-lightbox">
        <div v-if="preview" class="lx-lightbox" role="dialog" aria-modal="true" @click.self="closePreview">
          <button class="lx-lightbox-close" aria-label="关闭预览" @click="closePreview">✕</button>
          <div class="lx-lightbox-stage" @keydown.esc="closePreview">
            <button
              v-if="previewIndex > 0"
              class="lx-lightbox-nav prev"
              aria-label="上一张"
              @click.stop="step(-1)"
            >←</button>
            <img :src="preview.image_path" :alt="preview.title" />
            <button
              v-if="previewIndex < filteredImages.length - 1"
              class="lx-lightbox-nav next"
              aria-label="下一张"
              @click.stop="step(1)"
            >→</button>
          </div>
          <div class="lx-lightbox-meta">
            <span class="lx-lightbox-title">{{ preview.title || '未命名' }}</span>
            <span v-if="preview.description" class="lx-lightbox-desc">{{ preview.description }}</span>
          </div>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { LxCategory, LxImage } from '@/api/lixiangxiang'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ categories: LxCategory[]; images: LxImage[] }>()

const { rootRef, revealed } = useReveal()

const activeCat = ref('all')
const preview = ref<LxImage | null>(null)
const previewIndex = ref(-1)

function setCategory(id: string) {
  activeCat.value = id
  closePreview()
}

const filteredImages = computed(() => {
  if (activeCat.value === 'all') return props.images
  return props.images.filter(img => img.category_id === activeCat.value)
})

function openPreview(img: LxImage) {
  preview.value = img
  previewIndex.value = filteredImages.value.findIndex(x => x.id === img.id)
}

function closePreview() {
  preview.value = null
  previewIndex.value = -1
}

function step(dir: 1 | -1) {
  const list = filteredImages.value
  if (list.length === 0) return
  const next = (previewIndex.value + dir + list.length) % list.length
  preview.value = list[next]
  previewIndex.value = next
}

function onKeydown(e: KeyboardEvent) {
  if (!preview.value) return
  if (e.key === 'Escape') closePreview()
  if (e.key === 'ArrowLeft') step(-1)
  if (e.key === 'ArrowRight') step(1)
}

// 分类变化时重置预览
watch(activeCat, closePreview)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

// 键盘监听（Teleport 到 body 后仍可捕获）
window.addEventListener('keydown', onKeydown)
</script>

<style scoped>
.lx-section {
  padding: 110px 24px 120px;
  background: var(--bg-card);
  border-top: 1px dashed var(--border-default);
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
  margin: 0 0 40px;
  letter-spacing: 0.5px;
}

/* ================= Tabs ================= */
.lx-gallery-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 40px;
  padding-bottom: 20px;
  border-bottom: 1px dashed var(--border-default);
}

.lx-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 13.5px;
  cursor: pointer;
  transition: all 200ms var(--ease-out);
}

.lx-tab:hover {
  color: var(--accent);
}

.lx-tab.active {
  background: var(--text-primary);
  color: var(--bg-page);
}

.lx-tab-count {
  font-family: var(--font-mono);
  font-size: 11px;
  opacity: 0.7;
}

.lx-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 60px 0;
  font-family: var(--font-sans);
}

/* ================= 瀑布流（CSS columns） ================= */
.lx-masonry {
  column-count: 3;
  column-gap: 20px;
}

.lx-photo {
  margin: 0 0 20px;
  break-inside: avoid;
  border-radius: 12px;
  overflow: hidden;
  position: relative;
  cursor: zoom-in;
  background: var(--bg-page);
  box-shadow: var(--shadow-sm);
  transition: transform 250ms var(--ease-out), box-shadow 250ms var(--ease-out);
}

.lx-photo:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
}

.lx-photo img {
  width: 100%;
  height: auto;
  display: block;
  transition: transform 600ms var(--ease-out);
}

.lx-photo:hover img {
  transform: scale(1.03);
}

.lx-photo-caption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 40px 16px 13px;
  background: linear-gradient(180deg, transparent, rgba(10, 10, 8, 0.55));
  opacity: 0;
  transform: translateY(6px);
  transition: opacity 250ms var(--ease-out), transform 250ms var(--ease-out);
}

.lx-photo:hover .lx-photo-caption {
  opacity: 1;
  transform: none;
}

.lx-photo-title {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  color: #FFF8F2;
  letter-spacing: 0.3px;
}

/* ================= 手写灯箱 ================= */
.lx-lightbox {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(12, 11, 9, 0.88);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
}

.lx-lightbox-close {
  position: absolute;
  top: 20px;
  right: 24px;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: 1px solid rgba(255, 248, 242, 0.3);
  background: transparent;
  color: #FFF8F2;
  font-size: 17px;
  cursor: pointer;
  transition: background-color 200ms var(--ease-out), border-color 200ms var(--ease-out), transform 200ms var(--ease-out);
  z-index: 1;
}

.lx-lightbox-close:hover {
  background: rgba(255, 248, 242, 0.12);
  border-color: rgba(255, 248, 242, 0.6);
  transform: rotate(90deg);
}

.lx-lightbox-stage {
  position: relative;
  max-width: min(1080px, 94vw);
  max-height: 78vh;
}

.lx-lightbox-stage img {
  max-width: 100%;
  max-height: 78vh;
  border-radius: 10px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  display: block;
}

.lx-lightbox-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 46px;
  height: 46px;
  border-radius: 50%;
  border: 1px solid rgba(255, 248, 242, 0.3);
  background: rgba(255, 248, 242, 0.06);
  color: #FFF8F2;
  font-size: 18px;
  cursor: pointer;
  transition: background-color 200ms var(--ease-out);
}

.lx-lightbox-nav:hover {
  background: rgba(255, 248, 242, 0.18);
}

.lx-lightbox-nav.prev { left: -68px; }
.lx-lightbox-nav.next { right: -68px; }

.lx-lightbox-meta {
  margin-top: 22px;
  text-align: center;
  max-width: 640px;
}

.lx-lightbox-title {
  display: block;
  font-family: var(--font-display);
  font-size: 20px;
  color: #FFF8F2;
  letter-spacing: 1px;
  margin-bottom: 6px;
}

.lx-lightbox-desc {
  font-family: var(--font-sans);
  font-size: 14px;
  color: rgba(255, 248, 242, 0.72);
  line-height: 1.7;
}

/* 灯箱过渡 */
.lx-lightbox-enter-active,
.lx-lightbox-leave-active {
  transition: opacity 0.3s var(--ease-out);
}

.lx-lightbox-enter-from,
.lx-lightbox-leave-to {
  opacity: 0;
}

/* ================= Responsive ================= */
@media (max-width: 900px) {
  .lx-masonry {
    column-count: 2;
    column-gap: 14px;
  }

  .lx-photo {
    margin-bottom: 14px;
  }

  .lx-lightbox-nav.prev { left: -4px; }
  .lx-lightbox-nav.next { right: -4px; }
}

@media (max-width: 600px) {
  .lx-masonry {
    column-count: 1;
  }

  .lx-lightbox {
    padding: 32px 12px;
  }
}

@media (max-width: 768px) {
  .lx-section {
    padding: 72px 16px 88px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lx-section {
    opacity: 1;
    transform: none;
    transition: none;
  }

  .lx-photo, .lx-photo img { transition: none; }
  .lx-lightbox-close { transition: none; }
}
</style>