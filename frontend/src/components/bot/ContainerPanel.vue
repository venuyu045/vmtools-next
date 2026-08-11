<template>
  <div class="container-panel">
    <!-- 附加箱子扫描 -->
    <div class="scan-head">
      <span class="scan-title">附加箱子</span>
      <button class="pixel-btn mini outline" @click="scan" :disabled="scanning">扫描附近容器</button>
    </div>
    <div v-if="containers.length === 0 && !scanning" class="empty-text mono">未扫描 / 范围内无容器</div>
    <div v-else class="container-list">
      <div v-for="(c, i) in containers" :key="i" class="container-row" :class="{ active: isActive(c) }">
        <span class="mono cname">{{ zhBlock(c.name) }}</span>
        <span class="mono cpos">{{ c.x }}, {{ c.y }}, {{ c.z }}</span>
        <span class="mono cdist">{{ c.distance != null ? c.distance.toFixed(1) + 'm' : '' }}</span>
        <button class="pixel-btn mini" :disabled="busy" @click="goOpen(c)">{{ isActive(c) ? '已打开' : '前往' }}</button>
      </div>
    </div>

    <!-- 大箱子 UI（6 行 × 9 列；小箱子只显示上半 3 行） -->
    <div v-if="active" class="chest-area">
      <div class="chest-head">
        <span class="chest-title">{{ zhBlock(active.block_name) }} <span class="mono chest-pos">{{ active.position?.x }}, {{ active.position?.y }}, {{ active.position?.z }}</span></span>
        <span class="mono chest-rows">{{ isDouble ? '大箱子' : '小箱子' }} · {{ slotCount }} 格</span>
        <button class="pixel-btn mini outline" @click="refreshSnapshot" :disabled="loading">刷新</button>
        <button class="pixel-btn mini warning" @click="close">关闭</button>
      </div>
      <div class="chest-grid" :class="{ half: !isDouble }">
        <div v-for="idx in visibleSlots" :key="'cs'+idx"
          class="slot" :class="{ filled: !!getSlot(idx) }"
          :title="slotTip(idx)"
          @click="showDetail(idx)"
        >
          <ItemIcon v-if="getSlot(idx)" :item-id="getSlot(idx)!.item_id" :name="getSlot(idx)!.item_name_zh || getSlot(idx)!.name || getSlot(idx)!.item_id" :size="30" class="icon" />
          <span v-if="getSlot(idx)" class="count">{{ getSlot(idx)!.count }}</span>
        </div>
      </div>
    </div>
    <div v-else class="chest-empty mono">未打开容器 · 从上方列表「前往」打开</div>

    <!-- 物品详情 -->
    <el-dialog v-model="detail.show" :title="'容器物品'" width="360px" append-to-body>
      <div v-if="detail.item">
        <div class="detail-row"><b>物品</b><span>{{ detail.item.item_name_zh || detail.item.name || detail.item.item_id }}</span></div>
        <div class="detail-row"><b>数量</b><span>{{ detail.item.count }}</span></div>
        <div class="detail-row"><b>槽位</b><span class="mono">{{ detail.idx + 1 }} / {{ slotCount }}</span></div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { botApi } from '@/api/bot'
import ItemIcon from '@/components/ItemIcon.vue'

const props = defineProps<{ botId: string }>()

interface ContainerBlock { x: number; y: number; z: number; name: string; type?: string; distance?: number }
interface ChestSlot { item_id: string; name?: string; item_name_zh?: string; count: number }

const scanning = ref(false)
const busy = ref(false)
const loading = ref(false)
const containers = ref<ContainerBlock[]>([])
const active = ref<{ container_id: string; block_name: string; slot_count: number; position: { x: number; y: number; z: number } } | null>(null)
const items = ref<Map<number, ChestSlot>>(new Map())
const detail = ref({ show: false, item: null as ChestSlot | null, idx: -1 })

const slotCount = computed(() => active.value?.slot_count ?? 0)
const isDouble = computed(() => slotCount.value > 27) // 大箱子 54 / 末影箱 27 / 潜影盒 27
// 返回槽位索引数组 [0..n-1]（v-for 直接作为容器槽位索引；数字会被渲染为 1..n 造成槽位偏移）
const visibleSlots = computed(() => {
  const total = Math.min(slotCount.value, 54)
  const n = isDouble.value ? total : Math.min(total, 27)
  return Array.from({ length: n }, (_, i) => i)
})

const BLOCK_ZH: Record<string, string> = {
  chest: '箱子', trapped_chest: '陷阱箱', barrel: '木桶', ender_chest: '末影箱',
  shulker_box: '潜影盒', white_shulker_box: '白色潜影盒', orange_shulker_box: '橙色潜影盒',
  magenta_shulker_box: '品红色潜影盒', light_blue_shulker_box: '淡蓝色潜影盒',
  yellow_shulker_box: '黄色潜影盒', lime_shulker_box: '黄绿色潜影盒', pink_shulker_box: '粉色潜影盒',
  gray_shulker_box: '灰色潜影盒', light_gray_shulker_box: '淡灰色潜影盒',
  cyan_shulker_box: '青色潜影盒', purple_shulker_box: '紫色潜影盒', blue_shulker_box: '蓝色潜影盒',
  brown_shulker_box: '棕色潜影盒', green_shulker_box: '绿色潜影盒', red_shulker_box: '红色潜影盒',
  black_shulker_box: '黑色潜影盒',
}
function zhBlock(name: string): string {
  const n = String(name || '').replace(/^minecraft:/, '')
  return BLOCK_ZH[n] || n
}
function isActive(c: ContainerBlock) {
  return active.value && active.value.position?.x === c.x && active.value.position?.y === c.y && active.value.position?.z === c.z
}

// 切换 bot / 组件卸载时重置状态（避免显示上一个 bot 的容器/列表）
watch(() => props.botId, () => {
  active.value = null
  items.value = new Map()
  containers.value = []
  detail.value = { show: false, item: null, idx: -1 }
})
onBeforeUnmount(() => {
  if (active.value) { botApi.closeContainer(props.botId, active.value.container_id).catch(() => {}) }
  active.value = null
  items.value = new Map()
})

function getSlot(idx: number) { return items.value.get(idx) || null }
function slotTip(idx: number) {
  const s = getSlot(idx)
  return s ? `${s.item_name_zh || s.name || s.item_id} ×${s.count}` : '空'
}
function showDetail(idx: number) {
  const s = getSlot(idx)
  if (!s) return
  detail.value = { show: true, item: s, idx }
}

async function scan() {
  scanning.value = true
  try {
    const resp = await botApi.scanContainers(props.botId, 300)
    const blocks = resp.data?.blocks || []
    // 计算与 bot 的距离（后端不带距离时前端排序兜底）
    containers.value = blocks
    if (blocks.length === 0) ElMessage.info('未发现容器方块')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value = false
  }
}

async function goOpen(c: ContainerBlock) {
  busy.value = true
  try {
    const resp = await botApi.openContainer(props.botId, c.x, c.y, c.z)
    const d = resp.data
    if (!d?.container_id) { ElMessage.error(d?.error || '打开失败'); return }
    active.value = { container_id: d.container_id, block_name: d.block_name || c.name, slot_count: d.slot_count || 0, position: { x: c.x, y: c.y, z: c.z } }
    items.value = new Map()
    await refreshSnapshot()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '打开失败（可能被阻挡/无法交互）')
  } finally {
    busy.value = false
  }
}

async function refreshSnapshot() {
  if (!active.value) return
  loading.value = true
  try {
    const resp = await botApi.containerSnapshot(props.botId, active.value.container_id)
    const list = resp.data?.items || []
    const m = new Map<number, ChestSlot>()
    for (const it of list) {
      const slot = typeof it.slot === 'number' ? it.slot : it.slot_index
      if (slot == null) continue
      m.set(slot, {
        item_id: it.item_id || it.name || String(it.type != null ? it.type : ''),
        name: it.name || it.display_name || '',
        item_name_zh: it.item_name_zh || it.display_name_zh || '',
        count: it.count || 0,
      })
    }
    items.value = m
    // 槽位数以快照为准（大箱子 54 / 小箱子 27）
    if (resp.data?.slot_count) active.value.slot_count = resp.data.slot_count
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '读取容器失败')
  } finally {
    loading.value = false
  }
}

async function close() {
  if (!active.value) return
  try {
    await botApi.closeContainer(props.botId, active.value.container_id)
  } catch { /* 忽略 */ }
  active.value = null
  items.value = new Map()
}
</script>

<style scoped>
.container-panel { padding: 4px 0; user-select: none; }
.scan-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.scan-title { font-size: 14px; font-weight: 600; }
.empty-text { color: var(--text-muted); font-size: 12px; padding: 4px 0; }
.container-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; max-height: 180px; overflow: auto; }
.container-row {
  display: flex; align-items: center; gap: 10px; padding: 5px 8px;
  border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--bg-elevated);
}
.container-row.active { border-color: var(--green-primary, #67c23a); }
.cname { min-width: 72px; }
.cpos { flex: 1; font-size: 12px; }
.cdist { font-size: 12px; color: var(--text-muted); min-width: 48px; text-align: right; }
.chest-area { border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 8px; background: var(--bg-elevated); }
.chest-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.chest-title { font-size: 13px; font-weight: 600; }
.chest-pos { font-size: 12px; color: var(--text-muted); }
.chest-rows { font-size: 12px; color: var(--text-muted); }
.chest-grid {
  display: grid;
  grid-template-columns: repeat(9, 42px);
  gap: 3px;
  justify-content: flex-start;
}
.chest-grid.half { grid-template-rows: repeat(3, 42px); overflow: hidden; }
.slot {
  width: 42px; height: 42px; border: 2px solid #3a3a3a; border-radius: 3px;
  background: #141414; cursor: pointer; position: relative;
}
.slot:hover { border-color: #aaa; }
.slot.filled { background: #1a1a1a; }
.slot .count {
  position: absolute; right: 2px; bottom: 1px; font-size: 10px; color: #fff;
  text-shadow: 1px 1px 0 #000; font-family: var(--font-mono);
}
.chest-empty { color: var(--text-muted); font-size: 12px; padding: 12px 0; text-align: center; border: 1px dashed var(--border-default); border-radius: var(--radius-md); }
.detail-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--border-default); }
.detail-row:last-child { border-bottom: none; }
</style>
