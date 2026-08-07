<template>
  <div class="wh-items-page">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">{{ warehouse?.name || '仓库物品' }}</h2>
        <p v-if="warehouse" class="mono page-subtitle">
          {{ fmtBigNum(warehouse.container_count) }} 容器 | {{ fmtBigNum(warehouse.total_items) }} 物品
          <template v-if="warehouse.last_scan_time">| 上次扫描 {{ fmtTime(warehouse.last_scan_time) }}</template>
        </p>
      </div>
      <div class="header-actions">
        <el-input v-model="filter" placeholder="筛选物品..." clearable style="width: 220px" @input="filterItems" />
        <el-button @click="$router.push('/warehouse-status')">返回仓库状态</el-button>
      </div>
    </div>

    <!-- 物品详细列表 -->
    <el-card shadow="never">
      <div class="list-head">
        <h3>仓库物品（{{ filtered.length }} / {{ items.length }} 种）</h3>
      </div>

      <div v-if="filtered.length === 0" class="empty mono">-- 暂无物品数据，请先扫描仓库 --</div>
      <div v-else class="mat-table-wrap">
        <table class="mat-table">
          <thead>
            <tr>
              <th class="col-icon"></th>
              <th class="col-name">物品名称</th>
              <th class="col-id">物品 ID</th>
              <th class="col-count">数量</th>
              <th class="col-box">盒数</th>
              <th class="col-action"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in pagedItems" :key="item.item_id" class="mat-row">
              <td class="col-icon"><ItemIcon :item-id="item.item_id" :name="item.item_name_zh" :size="36" /></td>
              <td class="col-name">
                <span class="name-zh">{{ item.item_name_zh || item.display_name }}</span>
              </td>
              <td class="col-id mono muted">{{ item.item_id }}</td>
              <td class="col-count">
                <span class="count-val" :title="fmtExact(item.count)">{{ fmtBigNum(item.count) }}</span>
                <span class="count-exact mono muted">{{ fmtExact(item.count) }}</span>
              </td>
              <td class="col-box mono">{{ boxCount(item.count) }}盒</td>
              <td class="col-action">
                <el-button size="small" text type="primary" @click="openDetail(item)">箱子明细</el-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页 -->
      <div v-if="filtered.length > pageSize" class="pager">
        <el-pagination
          layout="prev, pager, next"
          :total="filtered.length"
          :page-size="pageSize"
          :current-page="page"
          @current-change="page = $event"
        />
      </div>
    </el-card>

    <!-- 物品箱子明细弹窗 -->
    <el-dialog v-model="detailOpen" :title="detailTitle" width="640px">
      <div v-if="detailLoading" class="mono muted detail-hint">加载箱子明细...</div>
      <div v-else-if="detailList.length" class="container-list">
        <div class="container-row head"><span>箱子坐标</span><span>槽位</span><span>储量</span></div>
        <div v-for="(c, idx) in detailList" :key="idx" class="container-row">
          <span class="mono">{{ c.x }}, {{ c.y }}, {{ c.z }}</span>
          <span class="mono muted">#{{ c.slot >= 0 ? c.slot : '--' }}</span>
          <span class="mono count">{{ fmtNum(c.count) }}</span>
        </div>
      </div>
      <div v-else class="mono muted detail-hint">（无箱子明细，请重新扫描仓库）</div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import ItemIcon from '@/components/ItemIcon.vue'
import { warehouseApi } from '@/api/warehouse'
import { boxCount, fmtBigNum, fmtExact } from '@/utils/format'

interface MatItem { item_id: string; display_name: string; item_name_zh: string; count: number }
interface DetailItem { x: number; y: number; z: number; count: number; slot: number }

const route = useRoute()
const warehouseId = computed(() => route.params.id as string)
const warehouse = ref<any>(null)
const items = ref<MatItem[]>([])
const filter = ref('')
const filtered = ref<MatItem[]>([])
const page = ref(1)
const pageSize = 100
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailList = ref<DetailItem[]>([])
const detailItem = ref<MatItem | null>(null)

const pagedItems = computed(() => {
  const start = (page.value - 1) * pageSize
  return filtered.value.slice(start, start + pageSize)
})

const detailTitle = computed(() => {
  if (!detailItem.value) return '箱子明细'
  return `${detailItem.value.item_name_zh || detailItem.value.display_name} 箱子明细`
})

function fmtNum(v: any): string {
  if (v == null || isNaN(Number(v))) return '0'
  return Number(v).toLocaleString()
}
function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch { return iso }
}

function filterItems() {
  const kw = filter.value.trim().toLowerCase()
  if (!kw) { filtered.value = items.value; page.value = 1; return }
  filtered.value = items.value.filter(it =>
    (it.item_name_zh || '').toLowerCase().includes(kw) ||
    it.item_id.toLowerCase().includes(kw) ||
    (it.display_name || '').toLowerCase().includes(kw)
  )
  page.value = 1
}

async function openDetail(item: MatItem) {
  detailItem.value = item
  detailOpen.value = true
  detailLoading.value = true
  detailList.value = []
  try {
    const { data } = await warehouseApi.searchItemDetails(item.item_id, 100)
    const hit = (data.items || []).find((r: any) => r.item_id === item.item_id)
    detailList.value = hit?.warehouses?.[0]?.containers || []
  } catch { detailList.value = [] }
  finally { detailLoading.value = false }
}

onMounted(async () => {
  try {
    const [{ data: wh }, { data: mats }] = await Promise.all([
      warehouseApi.get(warehouseId.value),
      warehouseApi.getMaterials(warehouseId.value, 1, 5000),
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
.header-actions { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
.list-head { margin-bottom: 12px; }
.list-head h3 { font-size: 14px; }

/* 详细列表表格 */
.mat-table-wrap { overflow-x: auto; border: 1px solid var(--border-subtle); }
.mat-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.mat-table thead th {
  background: #0a0a0a; color: var(--text-muted); font-weight: normal;
  text-align: left; padding: 8px 12px; font-size: 12px;
  border-bottom: 1px solid var(--border-subtle); white-space: nowrap;
}
.mat-table tbody tr { border-bottom: 1px solid var(--border-subtle); transition: background .15s; }
.mat-table tbody tr:hover { background: var(--green-glow); }
.mat-table td { padding: 6px 12px; vertical-align: middle; }
.col-icon { width: 48px; }
.col-name { min-width: 160px; }
.name-zh { color: var(--text-primary); font-weight: bold; }
.col-id { min-width: 200px; font-size: 12px; }
.col-count { min-width: 150px; white-space: nowrap; }
.count-val { color: var(--green-primary); font-size: 15px; margin-right: 8px; }
.count-exact { font-size: 11px; }
.col-box { color: #ffff00; white-space: nowrap; }
.col-action { text-align: right; white-space: nowrap; }

.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.empty { color: var(--text-muted); text-align: center; padding: 60px 0; }

.container-list { border: 1px solid var(--border-subtle); background: #000; max-height: 400px; overflow-y: auto; }
.container-row { display: grid; grid-template-columns: 1fr 80px 90px; gap: 8px; padding: 7px 12px; font-size: 12px; color: var(--text-secondary); border-bottom: 1px solid var(--border-subtle); }
.container-row:last-child { border-bottom: none; }
.container-row.head { color: var(--text-muted); font-size: 11px; }
.container-row .count { color: var(--green-primary); text-align: right; }
.detail-hint { font-size: 12px; padding: 10px 0; color: var(--text-muted); }

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .header-actions { width: 100%; }
  .header-actions .el-input { flex: 1; width: auto !important; }
  .col-id { min-width: 0; }
}
</style>