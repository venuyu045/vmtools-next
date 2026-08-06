<template>
  <div class="wh-status-page">
    <!-- 页头：搜索 -->
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">仓库状态</h2>
        <p class="mono page-subtitle">查看各仓库储量，按物品搜索「哪个仓库的哪个箱子存了什么」</p>
      </div>
      <div class="search-box">
        <el-input
          v-model="keyword"
          placeholder="搜索物品：中文名 / 英文名 / ID，如：钻石、diamond、nether_brick"
          clearable
          size="large"
          @keyup.enter="doSearch"
          @clear="clearResults"
        >
          <template #append>
            <el-button :loading="loading" @click="doSearch">搜索</el-button>
          </template>
        </el-input>
      </div>
    </div>

    <!-- 仓库概览 -->
    <el-card shadow="never" class="wh-overview">
      <div class="overview-head">
        <h3>现有仓库（{{ warehouses.length }}）</h3>
      </div>
      <div v-if="warehouses.length === 0" class="empty mono">-- 暂无仓库 --</div>
      <div v-else class="wh-cards">
        <div v-for="w in warehouses" :key="w.warehouse_id" class="wh-card pixel-card" @click="gotoWarehouse(w.warehouse_id)">
          <div class="wh-head">
            <span class="wh-name pixel">{{ w.name }}</span>
            <span class="wh-badge">{{ w.container_count }} 箱</span>
          </div>
          <div class="wh-stats">
            <div class="wh-stat"><span class="val">{{ fmtNum(w.total_items) }}</span><span class="lbl">物品总数</span></div>
            <div class="wh-stat"><span class="val yellow">{{ fmtNum(w.container_count) }}</span><span class="lbl">容器数</span></div>
            <div class="wh-stat"><span class="val small">{{ w.last_scan_time ? fmtTime(w.last_scan_time) : '--' }}</span><span class="lbl">上次扫描</span></div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 搜索结果 -->
    <el-card v-if="searched" shadow="never">
      <div class="result-head">
        <h3>搜索结果（{{ total }}）</h3>
        <span v-if="total === 0" class="mono muted">未找到匹配物品，试试中文名或英文名</span>
      </div>

      <div v-if="results.length" class="result-list">
        <div v-for="item in results" :key="item.item_id" class="item-card pixel-card">
          <div class="item-main" @click="toggleExpand(item)">
            <span class="item-icon" :style="{ background: iconBg(item.item_id) }">{{ itemEmoji(item.item_id) }}</span>
            <div class="item-info">
              <div class="item-name">{{ item.item_name_zh || item.display_name }}</div>
              <div class="item-id mono">{{ item.item_id }}</div>
            </div>
            <div class="item-count">
              <span class="count-val pixel">{{ fmtNum(item.total_count) }}</span>
              <span class="count-lbl mono">总储量</span>
            </div>
            <span class="expand-arrow" :class="{ open: expanded.has(item.item_id) }">▾</span>
          </div>

          <!-- 展开：各仓库储量 + 箱子明细 -->
          <div v-show="expanded.has(item.item_id)" class="item-detail">
            <div v-for="wh in item.warehouses" :key="wh.warehouse_id" class="wh-detail">
              <div class="wh-detail-head">
                <span class="wh-detail-name">{{ wh.warehouse_name }}</span>
                <span class="wh-detail-count pixel">{{ fmtNum(wh.count) }}</span>
              </div>
              <div v-if="wh.containers.length" class="container-list">
                <div class="container-row head">
                  <span>箱子坐标</span><span>槽位</span><span>储量</span>
                </div>
                <div v-for="(c, idx) in wh.containers" :key="idx" class="container-row">
                  <span class="mono">{{ c.x }}, {{ c.y }}, {{ c.z }}</span>
                  <span class="mono muted">#{{ c.slot >= 0 ? c.slot : '--' }}</span>
                  <span class="mono count">{{ fmtNum(c.count) }}</span>
                </div>
              </div>
              <div v-else class="mono muted detail-hint">（无箱子明细，请重新扫描仓库后查看具体位置）</div>
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { warehouseApi } from '@/api/warehouse'

interface ItemContainer { x: number; y: number; z: number; count: number; slot: number }
interface ItemWarehouse { warehouse_id: string; warehouse_name: string; count: number; containers: ItemContainer[] }
interface ItemResult {
  item_id: string; display_name: string; item_name_zh: string
  total_count: number; warehouses: ItemWarehouse[]
}

const router = useRouter()
const keyword = ref('')
const loading = ref(false)
const searched = ref(false)
const total = ref(0)
const results = ref<ItemResult[]>([])
const expanded = ref<Set<string>>(new Set())
const warehouses = ref<any[]>([])

function fmtNum(v: any): string {
  if (v == null || isNaN(Number(v))) return '0'
  return Number(v).toLocaleString()
}
function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch { return iso }
}
function gotoWarehouse(id: string) { router.push(`/warehouses/${id}`) }

/** 物品类别 → emoji 图标 */
function itemEmoji(itemId: string): string {
  const s = itemId.toLowerCase()
  if (s.includes('diamond')) return '💎'
  if (s.includes('emerald')) return '🟢'
  if (s.includes('netherite')) return '⚫'
  if (s.includes('gold')) return '🟡'
  if (s.includes('iron')) return '🔩'
  if (s.includes('coal')) return '⬛'
  if (s.includes('redstone')) return '🔴'
  if (s.includes('lapis')) return '🔵'
  if (s.includes('quartz')) return '🤍'
  if (s.includes('obsidian')) return '🟣'
  if (s.includes('shulker')) return '📦'
  if (s.includes('chest') || s.includes('barrel')) return '🧰'
  if (s.includes('log') || s.includes('plank') || s.includes('wood') || s.includes('bamboo')) return '🪵'
  if (s.includes('stone') || s.includes('cobblestone') || s.includes('deepslate') || s.includes('granite') || s.includes('andesite') || s.includes('diorite') || s.includes('tuff') || s.includes('calcite') || s.includes('sand') || s.includes('gravel') || s.includes('clay')) return '🪨'
  if (s.includes('brick') || s.includes('terracotta') || s.includes('concrete')) return '🧱'
  if (s.includes('glass') || s.includes('pane')) return '🪟'
  if (s.includes('soul') || s.includes('nether')) return '🔥'
  if (s.includes('cooked') || s.includes('beef') || s.includes('pork') || s.includes('chicken') || s.includes('fish') || s.includes('mutton')) return '🍖'
  if (s.includes('bread') || s.includes('apple') || s.includes('carrot') || s.includes('potato') || s.includes('melon') || s.includes('wheat') || s.includes('berry') || s.includes('egg') || s.includes('milk') || s.includes('pumpkin') || s.includes('beetroot')) return '🍎'
  if (s.includes('potion')) return '🧪'
  if (s.includes('sword')) return '⚔️'
  if (s.includes('pickaxe') || s.includes('axe') || s.includes('shovel') || s.includes('hoe')) return '⛏️'
  if (s.includes('helmet') || s.includes('chestplate') || s.includes('legging') || s.includes('boots')) return '🛡️'
  if (s.includes('bow') || s.includes('arrow') || s.includes('crossbow') || s.includes('trident')) return '🏹'
  if (s.includes('book') || s.includes('map') || s.includes('paper')) return '📖'
  if (s.includes('ender') || s.includes('dragon') || s.includes('chorus') || s.includes('pearl') || s.includes('eye')) return '👁️'
  if (s.includes('red')) return '🔴'
  if (s.includes('blue')) return '🔵'
  if (s.includes('green')) return '🟢'
  if (s.includes('yellow')) return '🟡'
  if (s.includes('white')) return '⚪'
  if (s.includes('black')) return '⚫'
  if (s.includes('flower') || s.includes('tulip') || s.includes('rose') || s.includes('dandelion') || s.includes('poppy') || s.includes('lily') || s.includes('allium') || s.includes('orchid') || s.includes('peony') || s.includes('sunflower') || s.includes('lilac')) return '🌸'
  return '📦'
}

/** 物品类别 → 图标底色 */
function iconBg(itemId: string): string {
  const s = itemId.toLowerCase()
  if (s.includes('diamond') || s.includes('emerald') || s.includes('lapis')) return 'rgba(80,200,255,.18)'
  if (s.includes('gold') || s.includes('yellow')) return 'rgba(255,210,80,.18)'
  if (s.includes('red') || s.includes('redstone')) return 'rgba(255,90,90,.18)'
  if (s.includes('green')) return 'rgba(120,220,120,.18)'
  if (s.includes('blue')) return 'rgba(90,140,255,.18)'
  if (s.includes('netherite') || s.includes('black') || s.includes('obsidian')) return 'rgba(150,120,200,.18)'
  if (s.includes('log') || s.includes('plank') || s.includes('wood')) return 'rgba(160,110,60,.18)'
  if (s.includes('stone') || s.includes('cobble') || s.includes('sand') || s.includes('gravel') || s.includes('brick') || s.includes('concrete') || s.includes('terracotta')) return 'rgba(150,150,150,.15)'
  if (s.includes('cooked') || s.includes('apple') || s.includes('bread') || s.includes('pork') || s.includes('beef')) return 'rgba(255,140,90,.18)'
  if (s.includes('potion') || s.includes('glass')) return 'rgba(180,120,255,.18)'
  return 'rgba(0,255,120,.12)'
}

function toggleExpand(item: ItemResult) {
  const next = new Set(expanded.value)
  if (next.has(item.item_id)) next.delete(item.item_id)
  else next.add(item.item_id)
  expanded.value = next
}

async function doSearch() {
  const q = keyword.value.trim()
  if (!q) { ElMessage.warning('请输入要搜索的物品'); return }
  loading.value = true
  try {
    const { data } = await warehouseApi.searchItemDetails(q, 50)
    results.value = data.items || []
    total.value = data.total || 0
    searched.value = true
    expanded.value = new Set()
  } catch (e: any) {
    ElMessage.error('搜索失败: ' + (e?.response?.data?.detail || e))
  } finally {
    loading.value = false
  }
}

function clearResults() {
  keyword.value = ''
  results.value = []
  total.value = 0
  searched.value = false
}

onMounted(async () => {
  try {
    const { data } = await warehouseApi.list()
    warehouses.value = data || []
  } catch { /* ignore */ }
})
</script>

<style scoped>
.wh-status-page { display: flex; flex-direction: column; gap: 18px; min-height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 6px; }
.page-subtitle { color: var(--text-secondary); font-size: 13px; }
.search-box { flex: 1; max-width: 560px; min-width: 260px; }

.wh-overview :deep(.el-card__body) { padding-bottom: 8px; }
.overview-head h3 { font-size: 14px; margin-bottom: 12px; color: var(--text-primary); }
.wh-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.wh-card { cursor: pointer; padding: 14px; }
.wh-card:hover { border-color: var(--border-active); }
.wh-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 8px; }
.wh-name { font-size: 14px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-badge { font-size: 12px; color: var(--green-primary); border: 1px solid var(--border-subtle); padding: 2px 8px; }
.wh-stats { display: flex; gap: 0; }
.wh-stat { flex: 1; display: flex; flex-direction: column; gap: 4px; padding-right: 14px; min-width: 0; }
.wh-stat:last-child { padding-right: 0; }
.wh-stat .val { font-size: 18px; color: var(--green-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-stat .val.yellow { color: #ffff00; }
.wh-stat .val.small { font-size: 12px; color: var(--text-secondary); }
.wh-stat .lbl { font-size: 12px; color: var(--text-secondary); }

.result-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.result-head h3 { font-size: 14px; }
.muted { color: var(--text-muted); }

.result-list { display: flex; flex-direction: column; gap: 10px; }
.item-card { padding: 0; overflow: hidden; }
.item-main { display: flex; align-items: center; gap: 12px; padding: 12px 14px; cursor: pointer; min-width: 0; }
.item-main:hover { background: var(--green-glow); }
.item-icon {
  width: 40px; height: 40px; flex-shrink: 0; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; border: 1px solid var(--border-subtle);
  background: rgba(0,255,120,.08);
}
.item-info { flex: 1; min-width: 0; }
.item-name { font-size: 15px; color: var(--text-primary); font-weight: bold; }
.item-id { font-size: 11px; color: var(--text-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item-count { text-align: right; flex-shrink: 0; }
.count-val { font-size: 18px; color: var(--green-primary); }
.count-lbl { font-size: 11px; color: var(--text-muted); display: block; }
.expand-arrow { color: var(--text-muted); transition: transform .2s; flex-shrink: 0; }
.expand-arrow.open { transform: rotate(180deg); }

.item-detail { border-top: 1px solid var(--border-subtle); background: #060606; padding: 12px 16px; }
.wh-detail { margin-bottom: 12px; }
.wh-detail:last-child { margin-bottom: 0; }
.wh-detail-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.wh-detail-name { font-size: 13px; color: var(--text-primary); }
.wh-detail-count { font-size: 15px; color: #ffff00; }
.container-list { border: 1px solid var(--border-subtle); background: #000; max-height: 260px; overflow-y: auto; }
.container-row { display: grid; grid-template-columns: 1fr 80px 90px; gap: 8px; padding: 6px 10px; font-size: 12px; color: var(--text-secondary); border-bottom: 1px solid var(--border-subtle); }
.container-row:last-child { border-bottom: none; }
.container-row.head { color: var(--text-muted); font-size: 11px; }
.container-row .count { color: var(--green-primary); text-align: right; }
.detail-hint { font-size: 12px; padding: 6px 0; }
.empty { color: var(--text-muted); text-align: center; padding: 40px 0; }

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .search-box { max-width: 100%; width: 100%; }
  .wh-cards { grid-template-columns: 1fr; }
  .item-main { gap: 8px; padding: 10px 12px; }
  .item-icon { width: 34px; height: 34px; font-size: 18px; }
  .container-row { grid-template-columns: 1fr 60px 70px; font-size: 11px; }
}
</style>