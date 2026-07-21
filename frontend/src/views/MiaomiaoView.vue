<template>
  <div class="miaomiao-page">
    <h2>🛠️ 妙妙工具</h2>
    <p class="subtitle">领地排行榜 · 标记点目录</p>

    <el-tabs v-model="activeTab" class="mm-tabs">
      <!-- Tab 1: 领地排行榜 -->
      <el-tab-pane label="🏠 领地排行榜" name="residences">
        <div class="tab-toolbar">
          <el-radio-group v-model="resSort" size="small" @change="refreshResTable">
            <el-radio-button value="area">按面积</el-radio-button>
            <el-radio-button value="owner">按所有者</el-radio-button>
          </el-radio-group>
          <el-input
            v-model="resSearch"
            placeholder="搜索领地或所有者..."
            size="small"
            clearable
            style="width: 220px"
            @input="refreshResTable"
          />
        </div>

        <el-table
          :data="filteredResidences"
          stripe
          size="small"
          max-height="500"
          empty-text="等 BlueMap 拉取数据..."
        >
          <el-table-column prop="label" label="领地名" min-width="140" />
          <el-table-column prop="owner" label="所有者" min-width="100" />
          <el-table-column prop="area" label="面积(块²)" width="120" sortable>
            <template #default="{ row }">
              {{ formatArea(row.area) }}
            </template>
          </el-table-column>
          <el-table-column label="坐标" min-width="160">
            <template #default="{ row }">
              <span v-if="row.position">
                {{ row.position.x.toFixed(0) }}, {{ row.position.y.toFixed(0) }}, {{ row.position.z.toFixed(0) }}
              </span>
              <span v-else class="na">--</span>
            </template>
          </el-table-column>
        </el-table>

        <!-- Owner rankings -->
        <div class="summary-box" v-if="resSort === 'owner' && playerStore.ownerRankings.length > 0">
          <h4>所有者排行榜</h4>
          <div class="owner-grid">
            <div v-for="(o, i) in playerStore.ownerRankings.slice(0, 20)" :key="o.owner" class="owner-item">
              <span class="owner-rank">{{ i + 1 }}</span>
              <span class="owner-name">{{ o.owner }}</span>
              <span class="owner-stats">{{ o.count }} 块领地 · {{ formatArea(o.totalArea) }}</span>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tab 2: 标记点目录 -->
      <el-tab-pane label="📍 标记点目录" name="markers">
        <div class="tab-toolbar">
          <el-input
            v-model="mkSearch"
            placeholder="搜索标记点..."
            size="small"
            clearable
            style="width: 260px"
          />
          <span class="mk-count">共 {{ filteredMarkers.length }} 个</span>
        </div>

        <div class="markers-grid">
          <div
            v-for="mk in filteredMarkers.slice(0, 200)"
            :key="mk.id"
            class="marker-card"
          >
            <div class="mk-name">{{ mk.label }}</div>
            <div class="mk-pos" v-if="mk.position">
              {{ mk.position.x.toFixed(0) }}, {{ mk.position.y.toFixed(0) }}, {{ mk.position.z.toFixed(0) }}
            </div>
            <div class="mk-detail" v-if="mk.detail">{{ mk.detail }}</div>
          </div>
        </div>
        <div v-if="filteredMarkers.length === 0 && playerStore.markers.length > 0" class="empty-hint">没有匹配的标记点</div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'
import client from '@/api/client'

const playerStore = useOnlinePlayersStore()
const activeTab = ref('residences')
const resSort = ref('area')
const resSearch = ref('')
const mkSearch = ref('')

// ── filtered tables ──

const rawResidences = ref<any[]>([])

onMounted(async () => {
  // Fetch residences/markers from API on mount (in case Socket.IO hasn't pushed yet)
  try {
    const { data: rd } = await client.get('/bluemap/residences')
    rawResidences.value = rd.residences || []
    playerStore.setResidences(rd.residences || [])
  } catch { /* Socket.IO will populate */ }
  try {
    const { data: md } = await client.get('/bluemap/markers')
    playerStore.setMarkers(md.markers || [])
  } catch { /* Socket.IO will populate */ }
})

const filteredResidences = computed(() => {
  let list = resSort.value === 'area'
    ? playerStore.residenceRankings
    : [...playerStore.residences]
  if (resSearch.value) {
    const q = resSearch.value.toLowerCase()
    list = list.filter(r =>
      r.label.toLowerCase().includes(q) || r.owner.toLowerCase().includes(q)
    )
  }
  return list
})

const filteredMarkers = computed(() => {
  let list = playerStore.markers
  if (mkSearch.value) {
    const q = mkSearch.value.toLowerCase()
    list = list.filter(m => m.label.toLowerCase().includes(q))
  }
  return list
})

function refreshResTable() { /* computed auto-refreshes */ }

function formatArea(v: number): string {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K'
  return v.toFixed(0)
}
</script>

<style scoped>
.miaomiao-page { max-width: 900px; margin: 0 auto; padding: 24px; }
.subtitle { color: var(--text-secondary); margin-bottom: 16px; }
.mm-tabs { margin-top: 16px; }

.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.mk-count { font-size: 13px; color: var(--text-disabled); }

/* Owner rankings */
.summary-box {
  margin-top: 20px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px;
}
.summary-box h4 { margin: 0 0 12px 0; font-size: 14px; }
.owner-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
@media (max-width: 600px) { .owner-grid { grid-template-columns: 1fr; } }
.owner-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: rgba(255,255,255,0.04);
  border-radius: 6px;
  font-size: 13px;
}
.owner-rank {
  font-weight: 700;
  color: var(--text-disabled);
  min-width: 20px;
}
.owner-name { font-weight: 600; flex: 1; }
.owner-stats { color: var(--text-secondary); font-size: 12px; }

/* Markers grid */
.markers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}
.marker-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
}
.mk-name { font-weight: 600; font-size: 14px; }
.mk-pos { color: var(--text-secondary); font-size: 11px; margin-top: 4px; }
.mk-detail { color: var(--text-disabled); font-size: 11px; margin-top: 4px; line-height: 1.4; }
.na { color: var(--text-disabled); font-style: italic; }
.empty-hint { color: var(--text-disabled); font-style: italic; font-size: 13px; text-align: center; padding: 24px; }
</style>
