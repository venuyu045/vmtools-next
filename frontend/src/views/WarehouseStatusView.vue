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
            <div class="wh-stat"><span class="val" :title="fmtExact(w.total_items)">{{ fmtBigNum(w.total_items) }}</span><span class="lbl">物品总数</span></div>
            <div class="wh-stat"><span class="val yellow">{{ fmtBigNum(w.container_count) }}</span><span class="lbl">容器数</span></div>
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
            <span class="item-icon-wrap"><ItemIcon :item-id="item.item_id" :name="item.item_name_zh" :size="40" /></span>
            <div class="item-info">
              <div class="item-name">{{ item.item_name_zh || item.display_name }}</div>
              <div class="item-id mono">{{ item.item_id }}</div>
            </div>
            <div class="item-count">
              <span class="count-val pixel">{{ fmtBigNum(item.total_count) }}</span>
              <span class="count-lbl mono" :title="fmtExact(item.total_count)">≈ {{ fmtExact(item.total_count) }}</span>
              <span class="count-lbl mono">≈ {{ boxCount(item.total_count) }}盒</span>
            </div>
            <span class="expand-arrow" :class="{ open: expanded.has(item.item_id) }">▾</span>
          </div>

          <!-- 展开：各仓库储量 + 箱子明细 -->
          <div v-show="expanded.has(item.item_id)" class="item-detail">
            <div v-for="wh in item.warehouses" :key="wh.warehouse_id" class="wh-detail">
              <div class="wh-detail-head">
                <span class="wh-detail-name">{{ wh.warehouse_name }}</span>
                <div class="wh-detail-nums">
                  <span class="wh-detail-count pixel">{{ fmtBigNum(wh.count) }}</span>
                  <span class="wh-detail-exact mono" :title="fmtExact(wh.count)">≈ {{ fmtExact(wh.count) }}</span>
                  <span class="wh-detail-box mono">≈ {{ boxCount(wh.count) }}盒</span>
                </div>
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
import ItemIcon from '@/components/ItemIcon.vue'
import { fmtApiTime } from '@/utils/time'
import { warehouseApi } from '@/api/warehouse'
import { boxCount, fmtBigNum, fmtExact } from '@/utils/format'
import { errMsg } from '@/utils/error'

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
  try { return fmtApiTime(iso, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch { return iso }
}
function gotoWarehouse(id: string) { router.push(`/warehouse-status/${id}`) }

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
    ElMessage.error(errMsg(e, '搜索失败'))
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
.page-title { color: var(--text-primary); font-family: var(--font-display); font-size: 24px; font-weight: 400; letter-spacing: -0.6px; margin-bottom: 6px; }
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
.wh-stat .val.yellow { color: var(--warning); }
.wh-stat .val.small { font-size: 12px; color: var(--text-secondary); }
.wh-stat .lbl { font-size: 12px; color: var(--text-secondary); }

.result-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.result-head h3 { font-size: 14px; }
.muted { color: var(--text-muted); }

.result-list { display: flex; flex-direction: column; gap: 10px; }
.item-card { padding: 0; overflow: hidden; }
.item-main { display: flex; align-items: center; gap: 12px; padding: 12px 14px; cursor: pointer; min-width: 0; }
.item-main:hover { background: var(--green-glow); }
.item-icon-wrap { flex-shrink: 0; display: flex; }
.item-info { flex: 1; min-width: 0; }
.item-name { font-size: 15px; color: var(--text-primary); font-weight: bold; }
.item-id { font-size: 11px; color: var(--text-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item-count { text-align: right; flex-shrink: 0; }
.count-val { font-size: 18px; color: var(--green-primary); }
.count-lbl { font-size: 11px; color: var(--text-muted); display: block; }
.expand-arrow { color: var(--text-muted); transition: transform .2s; flex-shrink: 0; }
.expand-arrow.open { transform: rotate(180deg); }

.item-detail { border-top: 1px solid var(--border-subtle); background: var(--bg-elevated); padding: 12px 16px; }
.wh-detail { margin-bottom: 12px; }
.wh-detail:last-child { margin-bottom: 0; }
.wh-detail-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px; flex-wrap: wrap; }
.wh-detail-name { font-size: 13px; color: var(--text-primary); min-width: 0; }
.wh-detail-nums { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.wh-detail-count { font-size: 15px; color: var(--warning); }
.wh-detail-exact { font-size: 11px; color: var(--text-muted); }
.wh-detail-box { font-size: 12px; color: var(--green-primary); white-space: nowrap; }
.container-list { border: 1px solid var(--border-subtle); background: var(--bg-card); max-height: 260px; overflow-y: auto; }
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
  .item-icon-wrap :deep(.item-icon) { width: 34px !important; height: 34px !important; }
  .container-row { grid-template-columns: 1fr 60px 70px; font-size: 11px; }
}

@media (max-width: 480px) {
  /* 超窄屏：搜索结果行换行布局——物品名/图标占首行，数量区换到第二行，
     避免数量（大数+精确值+盒数三行）与物品名互相挤压 */
  .item-main { flex-wrap: wrap; }
  .item-count {
    flex: 1 1 100%;
    display: flex;
    align-items: baseline;
    gap: 12px;
    text-align: left;
    padding-left: 0;
  }
  .count-lbl { display: inline; }
  .item-detail { padding: 10px 12px; }
  .wh-stats { flex-wrap: wrap; }
  .wh-stat { flex: 1 1 50%; padding-right: 8px; }
}
</style>