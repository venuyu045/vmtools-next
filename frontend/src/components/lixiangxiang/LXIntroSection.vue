<template>
  <section id="intro" ref="rootRef" class="lx-section lx-intro" :class="{ 'is-revealed': revealed }">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">About · 组织介绍</p>
      <h2 class="lx-section-title">一座由 22 位玩家共同筑造的生存之城</h2>

      <div class="lx-intro-grid">
        <div class="lx-intro-main">
          <div class="lx-prose" v-html="renderedIntro"></div>
        </div>

        <div class="lx-intro-side">
          <div class="lx-stat">
            <i class="lx-stat-pin"></i>
            <span class="lx-stat-num">{{ memberCount ?? 22 }}</span>
            <span class="lx-stat-label">位成员</span>
          </div>
          <div class="lx-stat">
            <i class="lx-stat-pin pin-blue"></i>
            <span class="lx-stat-num">{{ baseCount ?? 4 }}</span>
            <span class="lx-stat-label">座地图基地</span>
          </div>
          <div class="lx-stat">
            <i class="lx-stat-pin pin-moss"></i>
            <span class="lx-stat-num">{{ foundedYear }}</span>
            <span class="lx-stat-label">年建服</span>
          </div>
        </div>
      </div>

      <div class="lx-history">
        <h3 class="lx-history-title">发展历程</h3>
        <div class="lx-timeline" v-html="renderedHistory"></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { lxPublicApi } from '@/api/lixiangxiang'
import type { LxInfo } from '@/api/lixiangxiang'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{
  info: LxInfo | null
  /** 成员数量（Home 传入；缺省回退 seed 值 22） */
  memberCount?: number
  /** 基地数量（Home 传入；缺省回退 seed 值 4） */
  baseCount?: number
}>()

const { rootRef, revealed } = useReveal()

/** 组件独立使用时（未由 Home 预取传入）自动拉取 */
const localInfo = ref<LxInfo | null>(null)
const effectiveInfo = computed(() => props.info || localInfo.value)

/** 建服年份：优先 settings.founded（YYYY-MM 取前 4 位），缺省 2023 */
const foundedYear = computed(() => {
  const founded = effectiveInfo.value?.settings?.founded
  if (founded && /^\d{4}/.test(founded)) return founded.slice(0, 4)
  return '2023'
})

/** 简单渲染：**粗体** → <strong>，\n → 段落（先转义 HTML，防 XSS） */
function renderText(text: string): string {
  if (!text) return ''
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => `<p>${line}</p>`)
    .join('')
}

const renderedIntro = computed(() => renderText(effectiveInfo.value?.intro || ''))
const renderedHistory = computed(() => renderText(effectiveInfo.value?.history || ''))

onMounted(async () => {
  if (!props.info) {
    try {
      const { data } = await lxPublicApi.info()
      localInfo.value = data
    } catch { /* 忽略 */ }
  }
})
</script>

<style scoped>
.lx-section {
  padding: 110px 24px 96px;
  background: var(--bg-page);
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
  margin: 0 0 56px;
  letter-spacing: 2px;
  line-height: 1.25;
}

.lx-intro-grid {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 72px;
  align-items: start;
}

.lx-prose :deep(p) {
  font-family: var(--font-body);
  font-size: 17px;
  line-height: 2.15;
  color: var(--text-secondary);
  margin: 0 0 24px;
}

.lx-prose :deep(strong) {
  color: var(--accent);
  font-weight: 600;
}

/* ---- 细线条数据（无盒感，图钉标记） ---- */
.lx-intro-side {
  padding-top: 6px;
}

.lx-stat {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 0;
  border-bottom: 1px dashed var(--border-default);
}

.lx-stat-pin {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--lx-pin);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lx-pin) 25%, transparent);
  flex-shrink: 0;
}

.lx-stat-pin.pin-blue {
  background: var(--lx-blue);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lx-blue) 25%, transparent);
}

.lx-stat-pin.pin-moss {
  background: var(--lx-moss);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lx-moss) 25%, transparent);
}

.lx-stat-num {
  font-family: var(--font-display);
  font-size: 42px;
  line-height: 1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.lx-stat-label {
  font-family: var(--font-sans);
  font-size: 13.5px;
  color: var(--text-muted);
  letter-spacing: 1px;
}

/* ---- 时间线 ---- */
.lx-history {
  margin-top: 88px;
  padding-top: 64px;
  border-top: 1px dashed var(--border-default);
}

.lx-history-title {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 400;
  color: var(--text-primary);
  margin: 0 0 32px;
  letter-spacing: 1.5px;
}

.lx-timeline {
  position: relative;
  padding-left: 28px;
}

.lx-timeline::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: var(--border-default);
}

.lx-timeline :deep(p) {
  position: relative;
  margin: 0 0 22px;
  padding-left: 10px;
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.9;
  color: var(--text-secondary);
}

.lx-timeline :deep(p)::before {
  content: '';
  position: absolute;
  left: -26px;
  top: 9px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--bg-page);
  border: 1.5px solid var(--accent);
  transition: background-color 200ms var(--ease-out), transform 200ms var(--ease-out);
}

.lx-timeline :deep(p):hover::before {
  background: var(--accent);
  transform: scale(1.2);
}

/* ================= Responsive ================= */
@media (max-width: 900px) {
  .lx-intro-grid {
    grid-template-columns: 1fr;
    gap: 48px;
  }

  .lx-intro-side {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0;
  }

  .lx-stat {
    display: block;
    text-align: center;
    padding: 16px 8px;
  }

  .lx-stat + .lx-stat {
    border-left: 1px dashed var(--border-default);
  }
}

@media (max-width: 768px) {
  .lx-section {
    padding: 72px 16px 64px;
  }

  .lx-section-title {
    margin-bottom: 40px;
  }

  .lx-history {
    margin-top: 64px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lx-section {
    opacity: 1;
    transform: none;
    transition: none;
  }
}
</style>