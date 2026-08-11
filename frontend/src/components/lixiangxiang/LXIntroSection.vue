<template>
  <section id="intro" class="lx-section lx-intro">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">About</p>
      <h2 class="lx-section-title">组织介绍</h2>

      <div class="lx-intro-grid">
        <div class="lx-intro-main">
          <div class="lx-prose" v-html="renderedIntro"></div>
        </div>

        <div class="lx-intro-side">
          <div class="lx-stat-card">
            <div class="lx-stat-num">{{ memberCount ?? 22 }}</div>
            <div class="lx-stat-label">成员</div>
          </div>
          <div class="lx-stat-card">
            <div class="lx-stat-num">{{ baseCount ?? 4 }}</div>
            <div class="lx-stat-label">地图基地</div>
          </div>
          <div class="lx-stat-card">
            <div class="lx-stat-num">{{ foundedYear }}</div>
            <div class="lx-stat-label">建服年份</div>
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

const props = defineProps<{
  info: LxInfo | null
  /** 成员数量（Home 传入；缺省回退 seed 值 22） */
  memberCount?: number
  /** 基地数量（Home 传入；缺省回退 seed 值 4） */
  baseCount?: number
}>()

/** 建服年份：优先 settings.founded（YYYY-MM 取前 4 位），缺省 2023 */
const foundedYear = computed(() => {
  const founded = effectiveInfo.value?.settings?.founded
  if (founded && /^\d{4}/.test(founded)) return founded.slice(0, 4)
  return '2023'
})

/** 简单渲染：**粗体** → <strong>，\n → <br/>（不引入 markdown 依赖） */
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

/** 组件独立使用时（未由 Home 预取传入）自动拉取 */
const localInfo = ref<LxInfo | null>(null)
const effectiveInfo = computed(() => props.info || localInfo.value)

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
  margin: 0 0 48px;
  letter-spacing: 1px;
}

.lx-intro-grid {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 48px;
  align-items: start;
}

.lx-prose :deep(p) {
  font-family: var(--font-body);
  font-size: 16.5px;
  line-height: 2;
  color: var(--text-secondary);
  margin: 0 0 20px;
}

.lx-prose :deep(strong) {
  color: var(--accent);
  font-weight: 600;
}

.lx-intro-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.lx-stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  padding: 28px 24px;
  text-align: center;
  transition: transform 150ms var(--ease-out), border-color 150ms var(--ease-out), box-shadow 150ms var(--ease-out);
}

.lx-stat-card:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: var(--shadow-md);
}

.lx-stat-num {
  font-family: var(--font-display);
  font-size: 40px;
  color: var(--accent);
  line-height: 1;
  margin-bottom: 8px;
}

.lx-stat-label {
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text-muted);
}

.lx-history {
  margin-top: 72px;
  padding-top: 56px;
  border-top: 1px solid var(--border-subtle);
}

.lx-history-title {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 400;
  color: var(--text-primary);
  margin: 0 0 28px;
}

.lx-timeline :deep(p) {
  position: relative;
  padding-left: 22px;
  margin: 0 0 14px;
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.lx-timeline :deep(p)::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.6;
}

/* ================= Responsive ================= */
@media (max-width: 900px) {
  .lx-intro-grid {
    grid-template-columns: 1fr;
    gap: 32px;
  }

  .lx-intro-side {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .lx-stat-card {
    flex: 1;
    min-width: 120px;
  }
}

@media (max-width: 768px) {
  .lx-section {
    padding: 64px 16px;
  }

  .lx-section-title {
    margin-bottom: 32px;
  }
}
</style>