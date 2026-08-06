<template>
  <div class="miaomiao-page">
    <h2>🛠️ 妙妙工具</h2>
    <p class="subtitle">领地排行榜 · 标记点目录 · MSPT排行榜</p>

    <el-tabs v-model="activeTab" class="mm-tabs" @tab-change="onTabChange">
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
          <el-button size="small" :loading="refreshing" @click="refreshMarkers">🔄 刷新</el-button>
        </div>

        <el-table
          :data="filteredResidences.slice(0, 200)"
          stripe
          size="small"
          max-height="500"
          empty-text="等 BlueMap 拉取数据..."
        >
          <el-table-column label="世界" width="80">
            <template #default="{ row }">
              <span class="world-tag">{{ playerStore.getWorldLabel(row.world || 'world') }}</span>
            </template>
          </el-table-column>
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
          <el-button size="small" :loading="refreshing" @click="refreshMarkers">🔄 刷新</el-button>
        </div>

        <div class="markers-grid">
          <div
            v-for="mk in filteredMarkers.slice(0, 200)"
            :key="mk.id"
            class="marker-card"
          >
            <div class="mk-name">
              <span class="world-tag world-tag-sm">{{ playerStore.getWorldLabel(mk.world || 'world') }}</span>
              {{ mk.label }}
            </div>
            <div class="mk-pos" v-if="mk.position">
              {{ mk.position.x.toFixed(0) }}, {{ mk.position.y.toFixed(0) }}, {{ mk.position.z.toFixed(0) }}
            </div>
            <div class="mk-detail" v-if="mk.detail">{{ mk.detail }}</div>
          </div>
        </div>
        <div v-if="filteredMarkers.length === 0 && playerStore.markers.length > 0" class="empty-hint">没有匹配的标记点</div>
      </el-tab-pane>

      <!-- Tab 2.5: 服务器地标目录（新） -->
      <el-tab-pane label="🏛️ 服务器地标" name="landmarks">
        <div class="tab-toolbar">
          <el-input
            v-model="lmSearch"
            placeholder="搜索地标..."
            size="small"
            clearable
            style="width: 220px"
          />
          <span class="mk-count">共 {{ playerStore.landmarks.length }} 个地标 · {{ playerStore.landmarkTypes.length }} 类</span>
          <el-button size="small" :loading="refreshing" @click="refreshMarkers">🔄 刷新</el-button>
        </div>

        <!-- 类型统计 -->
        <div class="landmark-type-stats">
          <el-tag
            v-for="t in playerStore.landmarkTypes"
            :key="t.type"
            size="small"
            effect="plain"
            class="lm-type-tag"
            :type="activeLandmarkType === t.type ? 'primary' : 'info'"
            @click="activeLandmarkType = activeLandmarkType === t.type ? '' : t.type"
          >
            {{ t.type }} · {{ t.count }}
          </el-tag>
        </div>

        <div class="markers-grid">
          <div
            v-for="lm in filteredLandmarks.slice(0, 300)"
            :key="lm.id"
            class="marker-card"
          >
            <div class="mk-name">
              <span class="world-tag world-tag-sm">{{ playerStore.getWorldLabel(lm.world || 'world') }}</span>
              {{ lm.label }}
            </div>
            <div class="mk-pos" v-if="lm.position">
              {{ lm.position.x.toFixed(0) }}, {{ lm.position.y.toFixed(0) }}, {{ lm.position.z.toFixed(0) }}
            </div>
            <div class="mk-detail" v-if="lm.type"><span class="lm-type-badge">{{ lm.type }}</span></div>
            <div class="mk-detail" v-if="lm.detail">{{ lm.detail }}</div>
          </div>
        </div>
        <div v-if="filteredLandmarks.length === 0 && playerStore.landmarks.length > 0" class="empty-hint">没有匹配的地标</div>
      </el-tab-pane>

      <!-- Tab 2.6: 地铁线路（新） -->
      <el-tab-pane label="🚇 地铁线路" name="metro">
        <div class="tab-toolbar">
          <span class="mk-count">共 {{ playerStore.metroLines.length }} 条线路 · {{ playerStore.metroStations.length }} 个站点</span>
          <el-button size="small" :loading="refreshing" @click="refreshMarkers">🔄 刷新</el-button>
        </div>

        <div v-if="playerStore.metroLines.length === 0" class="empty-hint">暂无地铁线路数据</div>

        <div class="metro-lines-list">
          <div v-for="line in playerStore.metroLines" :key="line.id" class="metro-line-card">
            <div class="metro-line-header">
              <span class="metro-line-dot" :style="{ background: line.line_color || '#409eff' }"></span>
              <span class="metro-line-name">{{ line.label }}</span>
              <span class="world-tag world-tag-sm">{{ playerStore.getWorldLabel(line.world || 'world') }}</span>
            </div>
            <div class="metro-line-detail" v-if="line.detail">{{ line.detail }}</div>
            <div class="metro-line-meta" v-if="line.line && line.line.length">
              途经 {{ line.line.length }} 个坐标点
              <template v-if="line.position">
                · 起点 {{ line.position.x.toFixed(0) }}, {{ line.position.y.toFixed(0) }}, {{ line.position.z.toFixed(0) }}
              </template>
            </div>
          </div>
        </div>

        <div class="metro-stations-list" v-if="playerStore.metroStations.length > 0">
          <h4>站点</h4>
          <div class="markers-grid">
            <div v-for="st in playerStore.metroStations" :key="st.id" class="marker-card">
              <div class="mk-name">
                <span class="world-tag world-tag-sm">{{ playerStore.getWorldLabel(st.world || 'world') }}</span>
                {{ st.label }}
              </div>
              <div class="mk-pos" v-if="st.position">
                {{ st.position.x.toFixed(0) }}, {{ st.position.y.toFixed(0) }}, {{ st.position.z.toFixed(0) }}
              </div>
              <div class="mk-detail" v-if="st.detail">{{ st.detail }}</div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tab 3: 区域 MSPT 排行榜 -->
      <el-tab-pane label="⚡ MSPT排行榜" name="mspt">
        <div class="tab-toolbar">
          <el-radio-group v-model="msptSort" size="small">
            <el-radio-button value="mspt">按 MSPT</el-radio-button>
            <el-radio-button value="tps">按 TPS</el-radio-button>
            <el-radio-button value="entities">按实体数</el-radio-button>
            <el-radio-button value="players">按玩家数</el-radio-button>
          </el-radio-group>
          <el-input
            v-model="msptSearch"
            placeholder="搜索区域名..."
            size="small"
            clearable
            style="width: 200px"
          />
          <span class="mk-count">{{ filteredRegions.length }} 个区域</span>
          <el-button size="small" :loading="refreshing" @click="refreshMarkers">🔄 刷新</el-button>
        </div>

        <el-table
          :data="filteredRegions.slice(0, 500)"
          stripe
          size="small"
          max-height="500"
          empty-text="等 BlueMap 拉取区域数据..."
        >
          <el-table-column type="index" label="#" width="50" />
          <el-table-column label="世界" width="80">
            <template #default="{ row }">
              <span class="world-tag">{{ playerStore.getWorldLabel(row.world || 'world') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="玩家" min-width="160">
            <template #default="{ row }">
              <el-tooltip
                v-if="(playerStore.regionOnlinePlayers[`${row.world || 'world'}|${row.label}`]?.length || 0) > 0"
                placement="top"
                :show-after="300"
              >
                <template #content>
                  <div v-for="name in playerStore.regionOnlinePlayers[`${row.world || 'world'}|${row.label}`]" :key="name" style="line-height:1.6">{{ name }}</div>
                </template>
                <span class="region-link" style="font-weight:600">
                  {{ playerStore.regionOnlinePlayers[`${row.world || 'world'}|${row.label}`].join(', ') }}
                </span>
              </el-tooltip>
              <span v-else class="na">无人区域</span>
            </template>
          </el-table-column>
          <el-table-column label="附近领地" min-width="120">
            <template #default="{ row }">
              <el-tooltip
                v-if="(playerStore.regionResidences[row.id]?.length || 0) > 0"
                placement="top"
                :show-after="300"
              >
                <template #content>
                  <div v-for="r in playerStore.regionResidences[row.id]" :key="r" style="line-height:1.6">{{ r }}</div>
                </template>
                <span class="region-link">
                  {{ playerStore.regionResidences[row.id].length }} 个领地
                </span>
              </el-tooltip>
              <span v-else class="na">--</span>
            </template>
          </el-table-column>
          <el-table-column prop="mspt" label="MSPT (ms)" width="110" sortable>
            <template #default="{ row }">
              <span :class="msptClass(row.mspt)" class="perf-badge">
                {{ row.mspt != null ? row.mspt.toFixed(1) : '--' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="tps" label="TPS" width="80" sortable>
            <template #default="{ row }">
              <span :class="tpsClass(row.tps)" class="perf-badge">
                {{ row.tps != null ? row.tps.toFixed(1) : '--' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="entities" label="实体数" width="90" sortable />
          <el-table-column prop="chunks" label="区块" width="70" sortable />
          <el-table-column prop="sections" label="Section" width="80" sortable />
        </el-table>

        <!-- MSPT 颜色图例 -->
        <div class="legend-box">
          <span class="legend-title">颜色说明：</span>
          <span class="legend-item"><span class="dot dot-green"></span>MSPT ≤ 30（流畅）</span>
          <span class="legend-item"><span class="dot dot-orange"></span>MSPT ≤ 45（轻微卡顿）</span>
          <span class="legend-item"><span class="dot dot-red"></span>MSPT &gt; 45（严重卡顿）</span>
          <span class="legend-sep">|</span>
          <span class="legend-item"><span class="dot dot-green"></span>TPS ≥ 19.5</span>
          <span class="legend-item"><span class="dot dot-orange"></span>TPS ≥ 17</span>
          <span class="legend-item"><span class="dot dot-red"></span>TPS &lt; 17</span>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'
import client from '@/api/client'

defineOptions({ name: 'MiaomiaoView' })

const playerStore = useOnlinePlayersStore()
const route = useRoute()
// Support ?tab=mspt|residences|markers for deep links (e.g. QQ leaderboard link)
const activeTab = ref(['mspt', 'residences', 'markers', 'landmarks', 'metro'].includes(String(route.query.tab || ''))
  ? String(route.query.tab)
  : 'residences')
const resSort = ref('area')
const resSearch = ref('')
const mkSearch = ref('')
const lmSearch = ref('')
const activeLandmarkType = ref('')
const msptSort = ref('mspt')
const msptSearch = ref('')
const refreshing = ref(false)

// ── filtered tables ──

const rawResidences = ref<any[]>([])

// ── 按 tab 懒加载 ──────────────────────────────────────────────
// 进入页面只请求当前 tab 的数据；切换 tab 时按需加载该 tab（每个 tab 只请求一次）。
// 此前 onMounted 串行 await 6 个接口（每个等返回才发下一个）是"点击卡很久"的主因。
const loadedTabs = ref<Set<string>>(new Set())

async function loadTabData(tab: string) {
  if (loadedTabs.value.has(tab)) return
  loadedTabs.value.add(tab)
  try {
    if (tab === 'residences') {
      const { data: rd } = await client.get('/bluemap/residences')
      rawResidences.value = rd.residences || []
      playerStore.setResidences(rd.residences || [])
    } else if (tab === 'markers') {
      const { data: md } = await client.get('/bluemap/markers')
      playerStore.setMarkers(md.markers || [])
    } else if (tab === 'landmarks') {
      const { data: ld } = await client.get('/bluemap/landmarks')
      playerStore.setLandmarks(ld.landmarks || [])
    } else if (tab === 'metro') {
      const [ml, ms] = await Promise.all([
        client.get('/bluemap/metro-lines'),
        client.get('/bluemap/metro-stations'),
      ])
      playerStore.setMetroLines(ml.data.metro_lines || [])
      playerStore.setMetroStations(ms.data.metro_stations || [])
    } else if (tab === 'mspt') {
      const { data: rg } = await client.get('/bluemap/regions')
      playerStore.setRegions(rg.regions || [])
    }
  } catch { /* Socket.IO will populate */ }
}

function onTabChange() {
  void loadTabData(activeTab.value)
}

onMounted(() => {
  void loadTabData(activeTab.value)
})

const filteredResidences = computed(() => {
  let list = resSort.value === 'area'
    ? playerStore.residenceRankings
    : [...playerStore.residences]
  if (resSearch.value) {
    const q = resSearch.value.toLowerCase()
    list = list.filter(r =>
      r.label.toLowerCase().includes(q)
      || r.owner.toLowerCase().includes(q)
      || playerStore.getWorldLabel(r.world || 'world').toLowerCase().includes(q)
    )
  }
  return list
})

const filteredMarkers = computed(() => {
  let list = playerStore.markers
  if (mkSearch.value) {
    const q = mkSearch.value.toLowerCase()
    list = list.filter(m =>
      m.label.toLowerCase().includes(q)
      || playerStore.getWorldLabel(m.world || 'world').toLowerCase().includes(q)
    )
  }
  return list
})

const filteredLandmarks = computed(() => {
  let list = playerStore.landmarks
  if (activeLandmarkType.value) {
    list = list.filter(lm => (lm.type || '未分类') === activeLandmarkType.value)
  }
  if (lmSearch.value) {
    const q = lmSearch.value.toLowerCase()
    list = list.filter(lm =>
      lm.label.toLowerCase().includes(q)
      || (lm.type || '').toLowerCase().includes(q)
      || playerStore.getWorldLabel(lm.world || 'world').toLowerCase().includes(q)
    )
  }
  return list
})

function refreshResTable() { /* computed auto-refreshes */ }

async function refreshMarkers() {
  refreshing.value = true
  try {
    const { data: result } = await client.post('/bluemap/refresh')
    if (result.ok) {
      // Re-fetch all data after refresh
      const [rd, md, rg, ld, ml, ms] = await Promise.all([
        client.get('/bluemap/residences'),
        client.get('/bluemap/markers'),
        client.get('/bluemap/regions'),
        client.get('/bluemap/landmarks'),
        client.get('/bluemap/metro-lines'),
        client.get('/bluemap/metro-stations'),
      ])
      playerStore.setResidences(rd.data.residences || [])
      playerStore.setMarkers(md.data.markers || [])
      playerStore.setRegions(rg.data.regions || [])
      playerStore.setLandmarks(ld.data.landmarks || [])
      playerStore.setMetroLines(ml.data.metro_lines || [])
      playerStore.setMetroStations(ms.data.metro_stations || [])
      ElMessage.success(`刷新完成: ${result.residences} 领地, ${result.regions} 区域, ${result.markers} 标记, ${result.landmarks} 地标`)
    } else {
      ElMessage.error(result.message || '刷新失败')
    }
  } catch {
    ElMessage.error('刷新请求失败')
  } finally {
    refreshing.value = false
  }
}

function formatArea(v: number): string {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K'
  return v.toFixed(0)
}

// ── MSPT leaderboard ──

const filteredRegions = computed(() => {
  let list = [...playerStore.regions]
  if (msptSearch.value) {
    const q = msptSearch.value.toLowerCase()
    list = list.filter(r =>
      r.label.toLowerCase().includes(q)
      || playerStore.getWorldLabel(r.world || 'world').toLowerCase().includes(q)
    )
  }
  // Sort
  switch (msptSort.value) {
    case 'tps':
      list.sort((a, b) => (b.tps ?? 0) - (a.tps ?? 0))
      break
    case 'entities':
      list.sort((a, b) => (b.entities ?? 0) - (a.entities ?? 0))
      break
    case 'players':
      list.sort((a, b) => (b.players_in_region ?? 0) - (a.players_in_region ?? 0))
      break
    case 'mspt':
    default:
      list.sort((a, b) => (b.mspt ?? 0) - (a.mspt ?? 0))
      break
  }
  return list
})

function msptClass(v: number | null): string {
  if (v == null) return ''
  if (v <= 30) return 'mspt-good'
  if (v <= 45) return 'mspt-warn'
  return 'mspt-bad'
}

function tpsClass(v: number | null): string {
  if (v == null) return ''
  if (v >= 19.5) return 'tps-good'
  if (v >= 17) return 'tps-warn'
  return 'tps-bad'
}
</script>

<style scoped>
.miaomiao-page { max-width: 900px; margin: 0 auto; padding: 24px; }
.subtitle { color: var(--text-secondary); margin-bottom: 16px; }
.mm-tabs { margin-top: 16px; }

/* Fix Element Plus stripe row background in dark theme */
:deep(.el-table--striped .el-table__body tr.el-table__row--striped td) {
  background: rgba(255, 255, 255, 0.03) !important;
}
:deep(.el-table tr) {
  background: transparent !important;
}

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
.world-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  background: rgba(64, 158, 255, 0.15);
  color: #409eff;
  margin-right: 6px;
  white-space: nowrap;
}
.world-tag-sm { font-size: 10px; padding: 0 6px; vertical-align: 1px; }
.mk-pos { color: var(--text-secondary); font-size: 11px; margin-top: 4px; }
.mk-detail { color: var(--text-disabled); font-size: 11px; margin-top: 4px; line-height: 1.4; }
.na { color: var(--text-disabled); font-style: italic; }
.empty-hint { color: var(--text-disabled); font-style: italic; font-size: 13px; text-align: center; padding: 24px; }

/* MSPT / TPS badges */
.perf-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 12px;
}
.mspt-good, .tps-good { background: rgba(76, 175, 80, 0.18); color: #4caf50; }
.mspt-warn, .tps-warn { background: rgba(255, 152, 0, 0.18); color: #ff9800; }
.mspt-bad, .tps-bad   { background: rgba(244, 67, 54, 0.18); color: #f44336; }

/* Legend */
.legend-box {
  margin-top: 16px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 14px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.legend-title { font-weight: 600; margin-right: 4px; }
.legend-sep { color: var(--border-subtle); }
.legend-item { display: flex; align-items: center; gap: 4px; }
.dot {
  display: inline-block;
  width: 10px; height: 10px;
  border-radius: 50%;
}
.dot-green  { background: #4caf50; }
.dot-orange { background: #ff9800; }
.dot-red    { background: #f44336; }

.region-link {
  color: var(--text-primary);
  cursor: default;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
  max-width: 180px;
}

/* Landmark type stats & badges */
.landmark-type-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.lm-type-tag {
  cursor: pointer;
  transition: all 0.2s;
}
.lm-type-tag:hover {
  transform: translateY(-1px);
}
.lm-type-badge {
  display: inline-block;
  background: rgba(255, 152, 0, 0.15);
  color: #ff9800;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 600;
}

/* Metro lines */
.metro-lines-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}
.metro-line-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 16px;
}
.metro-line-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.metro-line-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}
.metro-line-name {
  font-weight: 600;
  font-size: 14px;
}
.metro-line-detail {
  color: var(--text-secondary);
  font-size: 12px;
  margin-top: 6px;
}
.metro-line-meta {
  color: var(--text-disabled);
  font-size: 11px;
  margin-top: 4px;
}
.metro-stations-list h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: var(--text-secondary);
}
</style>
