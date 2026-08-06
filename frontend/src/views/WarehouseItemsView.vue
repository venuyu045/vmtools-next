<template>
  <div class="wh-items-page">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">{{ warehouse?.name || '仓库物品' }}</h2>
        <p v-if="warehouse" class="mono page-subtitle">
          {{ fmtNum(warehouse.container_count) }} 容器 | {{ fmtNum(warehouse.total_items) }} 物品
          <template v-if="warehouse.last_scan_time">| 上次扫描 {{ fmtTime(warehouse.last_scan_time) }}</template>
        </p>
      </div>
      <div class="header-actions">
        <el-button @click="$router.push('/warehouse-status')">返回仓库状态</el-button>
      </div>
    </div>

    <!-- 物品列表 -->
    <el-card shadow="never">
      <div class="list-head">
        <h3>仓库物品（{{ items.length }} 种）</h3>
        <el-input v-model="filter" placeholder="筛选物品..." clearable style="width: 240px" @input="filterItems" />
      </div>

      <div v-if="filtered.length === 0" class="empty mono">-- 暂无物品数据，请先扫描仓库 --</div>
      <div v-else class="item-list">
        <div v-for="item in filtered" :key="item.item_id" class="item-row pixel-card">
          <div class="item-main" @click="toggleExpand(item)">
            <span class="item-icon" :style="{ background: iconBg(item.item_id) }">{{ itemEmoji(item.item_id) }}</span>
            <div class="item-info">
              <div class="item-name">{{ item.item_name_zh || item.display_name }}</div>
              <div class="item-id mono">{{ item.item_id }}</div>
            </div>
            <div class="item-count">
              <span class="count-val pixel">{{ fmtNum(item.count) }}</span>
              <span class="count-lbl mono">储量</span>
            </div>
            <span class="expand-arrow" :class="{ open: expanded.has(item.item_id) }">▾</span>
          </div>
          <!-- 展开：箱子明细 -->
          <div v-show="expanded.has(item.item_id)" class="item-detail">
            <div v-if="detailLoading.has(item.item_id)" class="mono muted detail-hint">加载箱子明细...</div>
            <div v-else-if="detailMap[item.item_id]?.length" class="container-list">
              <div class="container-row head"><span>箱子坐标</span><span>槽位</span><span>储量</span></div>
              <div v-for="(c, idx) in detailMap[item.item_id]" :key="idx" class="container-row">
                <span class="mono">{{ c.x }}, {{ c.y }}, {{ c.z }}</span>
                <span class="mono muted">#{{ c.slot >= 0 ? c.slot : '--' }}</span>
                <span class="mono count">{{ fmtNum(c.count) }}</span>
              </div>
            </div>
            <div v-else class="mono muted detail-hint">（无箱子明细，请重新扫描仓库）</div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { warehouseApi } from '@/api/warehouse'

interface MatItem { item_id: string; display_name: string; item_name_zh: string; count: number }
interface DetailItem { x: number; y: number; z: number; count: number; slot: number }

const route = useRoute()
const warehouseId = computed(() => route.params.id as string)
const warehouse = ref<any>(null)
const items = ref<MatItem[]>([])
const filter = ref('')
const filtered = ref<MatItem[]>([])
const expanded = ref<Set<string>>(new Set())
const detailMap = ref<Record<string, DetailItem[]>>({})
const detailLoading = ref<Set<string>>(new Set())

function fmtNum(v: any): string {
  if (v == null || isNaN(Number(v))) return '0'
  return Number(v).toLocaleString()
}
function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch { return iso }
}

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
  if (s.includes('stone') || s.includes('cobblestone') || s.includes('deepslate') || s.includes('granite') || s.includes('andesite') || s.includes('diorite') || s.includes('tuff') || s.includes('sand') || s.includes('gravel') || s.includes('clay')) return '🪨'
  if (s.includes('brick') || s.includes('terracotta') || s.includes('concrete')) return '🧱'
  if (s.includes('glass') || s.includes('pane')) return '🪟'
  if (s.includes('soul') || s.includes('nether')) return '🔥'
  if (s.includes('cooked') || s.includes('beef') || s.includes('pork') || s.includes('chicken') || s.includes('fish') || s.includes('mutton')) return '🍖'
  if (s.includes('bread') || s.includes('apple') || s.includes('carrot') || s.includes('potato') || s.includes('melon') || s.includes('wheat') || s.includes('berry') || s.includes('egg') || s.includes('milk') || s.includes('pumpkin') || s.includes('beetroot')) return '🍎'
  if (s.includes('potion')) return '🧪'
  if (s.includes('sword')) return '⚔️'
  if (s.includes('pickaxe') || s.includes('axe') || s.includes('shovel') || s.includes('hoe')) return '⛏️'
  if (s.includes('helmet') || s.includes('chestplate') || s.includes('legging') || s.includes('boots')) return '🛡️'
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

function filterItems() {
  const kw = filter.value.trim().toLowerCase()
  if (!kw) { filtered.value = items.value; return }
  filtered.value = items.value.filter(it =>
    (it.item_name_zh || '').toLowerCase().includes(kw) ||
    it.item_id.toLowerCase().includes(kw) ||
    (it.display_name || '').toLowerCase().includes(kw)
  )
}

async function toggleExpand(item: MatItem) {
  const next = new Set(expanded.value)
  if (next.has(item.item_id)) { next.delete(item.item_id); expanded.value = next; return }
  next.add(item.item_id)
  expanded.value = next
  if (!detailMap.value[item.item_id] && !detailLoading.value.has(item.item_id)) {
    detailLoading.value.add(item.item_id)
    try {
      const { data } = await warehouseApi.searchItemDetails(item.item_id, 50)
      const hit = (data.items || []).find((r: any) => r.item_id === item.item_id)
      detailMap.value[item.item_id] = hit?.warehouses?.[0]?.containers || []
    } catch { detailMap.value[item.item_id] = [] }
    finally { detailLoading.value.delete(item.item_id) }
  }
}

onMounted(async () => {
  try {
    const [{ data: wh }, { data: mats }] = await Promise.all([
      warehouseApi.get(warehouseId.value),
      warehouseApi.getMaterials(warehouseId.value, 1, 500),
    ])
    warehouse.value = wh
    items.value = (mats.items || []).sort((a: any, b: any) => (b.count || 0) - (a.count || 0))
    filtered.value = items.value
  } catch (e: any) {
    ElMessage.error('加载仓库数据失败: ' + (e?.response?.data?.detail || e))
  }
})
</script>

<style scoped>
.wh-items-page { display: flex; flex-direction: column; gap: 18px; min-height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 6px; }
.page-subtitle { color: var(--text-secondary); font-size: 13px; }
.header-actions { flex-shrink: 0; }
.list-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.list-head h3 { font-size: 14px; }

.item-list { display: flex; flex-direction: column; gap: 10px; }
.item-row { padding: 0; overflow: hidden; }
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
.container-list { border: 1px solid var(--border-subtle); background: #000; max-height: 280px; overflow-y: auto; }
.container-row { display: grid; grid-template-columns: 1fr 80px 90px; gap: 8px; padding: 6px 10px; font-size: 12px; color: var(--text-secondary); border-bottom: 1px solid var(--border-subtle); }
.container-row:last-child { border-bottom: none; }
.container-row.head { color: var(--text-muted); font-size: 11px; }
.container-row .count { color: var(--green-primary); text-align: right; }
.detail-hint { font-size: 12px; padding: 6px 0; }
.empty { color: var(--text-muted); text-align: center; padding: 60px 0; }

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .list-head { flex-direction: column; align-items: stretch; }
  .list-head .el-input { width: 100% !important; }
  .item-main { gap: 8px; padding: 10px 12px; }
  .item-icon { width: 34px; height: 34px; font-size: 18px; }
  .container-row { grid-template-columns: 1fr 60px 70px; font-size: 11px; }
}
</style>