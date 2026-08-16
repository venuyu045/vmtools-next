<template>
  <section id="members" ref="rootRef" class="lx-section lx-members" :class="{ 'is-revealed': revealed }">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Members · 同乡</p>
      <h2 class="lx-section-title">共聚理想乡 · {{ members.length }} 位成员</h2>

      <div class="lx-toolbar">
        <div class="lx-filter" role="tablist" aria-label="按职位筛选">
          <button
            class="lx-chip"
            :class="{ active: activeFilter === '全部' }"
            @click="setFilter('全部')"
          >全部</button>
          <button
            v-for="t in titleOptions"
            :key="t"
            class="lx-chip"
            :class="{ active: activeFilter === t }"
            @click="setFilter(t)"
          >{{ t }}</button>
        </div>

        <div class="lx-sort">
          <span class="lx-sort-label">排序</span>
          <button
            class="lx-sort-btn"
            :class="{ active: sortMode === 'join' }"
            @click="toggleSort('join')"
          >加入时间{{ sortMode === 'join' ? (sortAsc ? '↑' : '↓') : '' }}</button>
          <button
            class="lx-sort-btn"
            :class="{ active: sortMode === 'rank' }"
            @click="toggleSort('rank')"
          >默认顺序{{ sortMode === 'rank' ? (sortAsc ? '↑' : '↓') : '' }}</button>
        </div>
      </div>

      <div v-if="filteredMembers.length === 0" class="lx-empty">暂无成员</div>

      <div v-else class="lx-member-grid">
        <article
          v-for="(m, i) in filteredMembers"
          :key="m.id"
          class="lx-member-card"
          :class="{ 'is-wide': (i % 6) === 0 }"
        >
          <div class="lx-avatar">
            <img v-if="m.avatar_path" :src="m.avatar_path" :alt="m.nickname || m.game_id" loading="lazy" />
            <span v-else class="lx-avatar-fallback">{{ (m.nickname || m.game_id).slice(0, 1) }}</span>
          </div>
          <div class="lx-member-info">
            <div class="lx-member-name">
              <span class="lx-nickname">{{ m.nickname || m.game_id }}</span>
              <span class="lx-gameid">{{ m.game_id }}</span>
            </div>
            <div class="lx-member-title">{{ m.title || '成员' }}</div>
            <div class="lx-member-meta">
              <span v-if="m.joined_at" class="lx-meta-item">{{ m.joined_at }} 加入</span>
              <span v-if="m.specialty" class="lx-meta-item">{{ m.specialty }}</span>
            </div>
            <p v-if="m.bio" class="lx-member-bio" :class="{ 'bio-full': (i % 6) === 0 }">{{ m.bio }}</p>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LxMember } from '@/api/lixiangxiang'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ members: LxMember[] }>()

const { rootRef, revealed } = useReveal()

const activeFilter = ref('全部')
const sortMode = ref<'join' | 'rank'>('rank')
const sortAsc = ref(true)

/** 职位/称号筛选项（按出现次数取前 8 个常见职位） */
const titleOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const m of props.members) {
    const t = m.title || '成员'
    counts.set(t, (counts.get(t) || 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t]) => t)
})

function setFilter(t: string) {
  activeFilter.value = t
}

function toggleSort(mode: 'join' | 'rank') {
  if (sortMode.value === mode) {
    sortAsc.value = !sortAsc.value
  } else {
    sortMode.value = mode
    sortAsc.value = true
  }
}

const filteredMembers = computed(() => {
  let list = props.members
  if (activeFilter.value !== '全部') {
    list = list.filter(m => (m.title || '成员') === activeFilter.value)
  }
  const sorted = [...list]
  if (sortMode.value === 'join') {
    sorted.sort((a, b) => {
      const ka = (a.joined_at || '').replace(/[^\d]/g, '')
      const kb = (b.joined_at || '').replace(/[^\d]/g, '')
      const diff = (ka || '0').localeCompare(kb || '0')
      return sortAsc ? diff : -diff
    })
  } else {
    sorted.sort((a, b) => (sortAsc ? a.sort_order - b.sort_order : b.sort_order - a.sort_order))
  }
  return sorted
})

// 成员列表变化（如管理端保存后返回）时重置筛选
watch(() => props.members.length, () => {
  activeFilter.value = '全部'
})
</script>

<style scoped>
.lx-section {
  padding: 110px 24px 96px;
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
  margin: 0 0 40px;
  letter-spacing: 2px;
  line-height: 1.25;
}

/* ================= Toolbar（去胶囊化） ================= */
.lx-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 44px;
  padding-bottom: 20px;
  border-bottom: 1px dashed var(--border-default);
}

.lx-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.lx-chip {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms var(--ease-out);
}

.lx-chip:hover {
  color: var(--accent);
}

.lx-chip.active {
  background: var(--text-primary);
  border-color: var(--text-primary);
  color: var(--bg-page);
}

.lx-sort {
  display: flex;
  align-items: center;
  gap: 6px;
}

.lx-sort-label {
  font-family: var(--font-sans);
  font-size: 12.5px;
  color: var(--text-muted);
  letter-spacing: 0.5px;
}

.lx-sort-btn {
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms var(--ease-out);
}

.lx-sort-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.lx-sort-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}

.lx-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 60px 0;
  font-family: var(--font-sans);
}

/* ================= 6 列错落杂志式网格 ================= */
.lx-member-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

/* 每 6 张中第 1 张为宽卡（跨 4 列），其余为 2 列窄卡 → 大卡+两窄卡 / 三窄卡交替 */
.lx-member-card {
  grid-column: span 2;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 22px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  transition: transform 250ms var(--ease-out), box-shadow 250ms var(--ease-out), border-color 250ms var(--ease-out);
}

.lx-member-card.is-wide {
  grid-column: span 4;
  flex-direction: row;
  align-items: center;
  gap: 24px;
  padding: 26px 28px;
}

.lx-member-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-md);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border-subtle));
}

.lx-avatar {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  transition: transform 250ms var(--ease-out);
}

.lx-member-card:hover .lx-avatar {
  transform: scale(1.04);
}

.lx-member-card.is-wide .lx-avatar {
  width: 84px;
  height: 84px;
  border-radius: 16px;
}

.lx-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.lx-avatar-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 22px;
  color: var(--accent);
  background: var(--accent-soft);
}

.lx-member-info {
  flex: 1;
  min-width: 0;
}

.lx-member-name {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.lx-nickname {
  font-family: var(--font-display);
  font-size: 19px;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.lx-gameid {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
}

.lx-member-title {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 5px;
  background: var(--accent-soft);
  color: var(--accent);
  font-family: var(--font-sans);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  margin-bottom: 10px;
}

.lx-member-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-family: var(--font-sans);
  font-size: 12.5px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.lx-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.lx-meta-item::before {
  content: '';
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.45;
}

.lx-member-bio {
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-secondary);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.lx-member-bio.bio-full {
  -webkit-line-clamp: 3;
  font-size: 13.5px;
}

/* ================= Responsive ================= */
@media (max-width: 1024px) {
  .lx-member-grid {
    grid-template-columns: repeat(4, 1fr);
  }

  .lx-member-card,
  .lx-member-card.is-wide {
    grid-column: span 2;
    flex-direction: column;
    align-items: stretch;
    padding: 20px;
  }

  .lx-member-card.is-wide .lx-avatar {
    width: 56px;
    height: 56px;
    border-radius: 12px;
  }
}

@media (max-width: 768px) {
  .lx-section {
    padding: 72px 16px 64px;
  }

  .lx-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .lx-member-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }

  .lx-member-card,
  .lx-member-card.is-wide {
    grid-column: span 1;
    padding: 16px;
  }
}

@media (max-width: 480px) {
  .lx-member-grid {
    grid-template-columns: 1fr;
  }

  .lx-member-card,
  .lx-member-card.is-wide {
    flex-direction: row;
    align-items: center;
    grid-column: span 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lx-section {
    opacity: 1;
    transform: none;
    transition: none;
  }

  .lx-member-card { transition: none; }
  .lx-avatar { transition: none; }
}
</style>