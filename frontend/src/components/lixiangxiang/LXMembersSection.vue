<template>
  <section id="members" class="lx-section lx-members">
    <div class="lx-section-inner">
      <p class="lx-eyebrow">Members</p>
      <h2 class="lx-section-title">成员 · 22 位</h2>

      <div class="lx-toolbar">
        <div class="lx-filter">
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
          >加入时间{{ sortMode === 'join' ? (sortAsc ? ' ↑' : ' ↓') : '' }}</button>
          <button
            class="lx-sort-btn"
            :class="{ active: sortMode === 'rank' }"
            @click="toggleSort('rank')"
          >默认顺序{{ sortMode === 'rank' ? (sortAsc ? ' ↑' : ' ↓') : '' }}</button>
        </div>
      </div>

      <div v-if="filteredMembers.length === 0" class="lx-empty">暂无成员</div>

      <div class="lx-member-grid">
        <article v-for="m in filteredMembers" :key="m.id" class="lx-member-card">
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
              <span v-if="m.joined_at" class="lx-meta-item"><i class="lx-meta-dot"></i>{{ m.joined_at }} 加入</span>
              <span v-if="m.specialty" class="lx-meta-item"><i class="lx-meta-dot"></i>{{ m.specialty }}</span>
            </div>
            <p v-if="m.bio" class="lx-member-bio">{{ m.bio }}</p>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LxMember } from '@/api/lixiangxiang'

const props = defineProps<{ members: LxMember[] }>()

const activeFilter = ref('全部')
const sortMode = ref<'join' | 'rank'>('rank')
const sortAsc = ref(true)

/** 职位/称号筛选项（前 8 个常见职位 + 其余归入「其他」） */
const titleOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const m of props.members) {
    const t = m.title || '成员'
    counts.set(t, (counts.get(t) || 0) + 1)
  }
  const options = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t]) => t)
  return options
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
  margin: 0 0 32px;
  letter-spacing: 1px;
}

/* ================= Toolbar ================= */
.lx-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 40px;
}

.lx-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.lx-chip {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--border-default);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  cursor: pointer;
  transition: all 150ms var(--ease-out);
}

.lx-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.lx-chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #FFF8F2;
}

.lx-sort {
  display: flex;
  align-items: center;
  gap: 8px;
}

.lx-sort-label {
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-muted);
}

.lx-sort-btn {
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid var(--border-default);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  cursor: pointer;
  transition: all 150ms var(--ease-out);
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

/* ================= Member Grid ================= */
.lx-member-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.lx-member-card {
  display: flex;
  gap: 18px;
  padding: 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  transition: transform 150ms var(--ease-out), border-color 150ms var(--ease-out), box-shadow 150ms var(--ease-out);
}

.lx-member-card:hover {
  transform: translateY(-3px);
  border-color: var(--accent);
  box-shadow: var(--shadow-md);
}

.lx-avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  border: 2px solid var(--accent-soft);
  background: var(--bg-elevated);
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
  font-size: 24px;
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
  margin-bottom: 4px;
}

.lx-nickname {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--text-primary);
}

.lx-gameid {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
}

.lx-member-title {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 10px;
}

.lx-member-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.lx-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.lx-meta-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.5;
  flex-shrink: 0;
}

.lx-member-bio {
  font-family: var(--font-sans);
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ================= Responsive ================= */
@media (max-width: 768px) {
  .lx-section {
    padding: 64px 16px;
  }

  .lx-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .lx-member-grid {
    grid-template-columns: 1fr;
  }
}
</style>