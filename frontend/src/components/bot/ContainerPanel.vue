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
        <button class="pixel-btn mini" :disabled="busy || activating" @click="goOpen(c)">{{ isActive(c) ? '已打开' : '前往' }}</button>
        <button class="pixel-btn mini outline" :disabled="busy || activating" title="右键该方块（箱子 UI / 快捷潜影盒触发）" @click="goActivate(c)">右键</button>
      </div>
    </div>

    <!-- 大箱子 UI（6 行 × 9 列；小箱子只显示上半 3 行） -->
      <div v-if="active" class="chest-area">
        <div class="chest-head">
          <span class="chest-title">{{ zhBlock(active.block_name) }} <span class="mono chest-pos">{{ active.position?.x }}, {{ active.position?.y }}, {{ active.position?.z }}</span></span>
          <span class="mono chest-rows">{{ isDouble ? '大箱子' : '小箱子' }} · {{ slotCount }} 格</span>
          <button class="pixel-btn mini outline" @click="refreshSnapshot" :disabled="loading">刷新</button>
          <button class="pixel-btn mini" @click="goBack" :disabled="stack.length <= 1" title="关闭当前窗口，由服务器返回上一层容器">返回上一层</button>
          <button class="pixel-btn mini warning" @click="close">关闭</button>
        </div>
        <div v-if="stack.length > 1" class="window-chain mono">窗口链：已打开 {{ stack.length }} 层（关闭子窗口后自动返回上层）</div>
        <!-- 窗口点击提示：左键=拿起/放下整组 · 右键=拿/放半组（快捷潜影盒右键物品可开新窗） -->
        <div class="click-hint" v-if="active">
          <span :class="{ holding }">左键=拿/放整组</span>
          <span>右键=拿/放半组</span>
          <span v-if="holding" class="holding-text">已拿起，点目标槽放下 / 点虚空丢弃</span>
        </div>
        <div class="chest-grid" :class="{ half: !isDouble }">
          <div v-for="idx in visibleSlots" :key="'cs'+idx"
            class="slot" :class="{ filled: !!getSlot(idx), holding: holdingSlot === idx }"
            :title="slotTip(idx)"
            @click="onSlotClick(idx)"
            @click.right.prevent="onSlotRight(idx)"
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
        <div v-if="detail.item.custom_name" class="detail-row"><b>命名</b><span class="custom-name">{{ detail.item.custom_name }}</span></div>
        <div v-if="detail.item.lore && detail.item.lore.length" class="detail-row lore-row"><b>描述</b><span class="lore-list"><div v-for="(l, i) in detail.item.lore" :key="i" class="lore-line">{{ l }}</div></span></div>
        <div class="detail-row"><b>数量</b><span>{{ detail.item.count }}</span></div>
        <div class="detail-row"><b>槽位</b><span class="mono">{{ detail.idx + 1 }} / {{ slotCount }}</span></div>
        <div class="detail-actions">
          <el-button size="small" type="primary" @click="doPickup">拿起（左键）</el-button>
          <el-button size="small" @click="detail.show = false">取消</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { botApi } from '@/api/bot'
import { useSocketIO } from '@/composables/useSocketIO'
import ItemIcon from '@/components/ItemIcon.vue'
import { errMsg } from '@/utils/error'

const props = defineProps<{ botId: string }>()
const { on: sockOn, off: sockOff } = useSocketIO()

interface ContainerBlock { x: number; y: number; z: number; name: string; type?: string; distance?: number }
interface ChestSlot { item_id: string; name?: string; item_name_zh?: string; count: number; custom_name?: string | null; lore?: string[] }

const scanning = ref(false)
const busy = ref(false)
const activating = ref(false)  // 右键方块进行中
const loading = ref(false)
const containers = ref<ContainerBlock[]>([])
const active = ref<{ container_id: string; block_name: string; slot_count: number; position: { x: number; y: number; z: number } } | null>(null)
const items = ref<Map<number, ChestSlot>>(new Map())
const detail = ref({ show: false, item: null as ChestSlot | null, idx: -1 })
// 窗口点击状态（2026-08-12）
const holding = ref(false)          // 是否手持物品（左键拿起后为 true）
const holdingSlot = ref(-1)         // 拿起来源槽位（高亮）
const clicking = ref(false)         // 点击请求进行中（防连点）
const stack = ref<string[]>([])     // 窗口链（container_id 打开顺序，嵌套窗口返回用）

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
  holding.value = false
  holdingSlot.value = -1
  stack.value = []
})
onMounted(() => {
  sockOn('mf_container_opened', onContainerOpened)
  sockOn('mf_container_closed', onContainerClosed)
  window.addEventListener('vmt:gui-opened', onGuiOpened)
  // 常驻面板：挂载时查询当前已打开的窗口（GUI / 容器），有则直接显示
  syncCurrentWindow()
})
onBeforeUnmount(() => {
  sockOff('mf_container_opened', onContainerOpened)
  sockOff('mf_container_closed', onContainerClosed)
  window.removeEventListener('vmt:gui-opened', onGuiOpened)
  if (active.value) { botApi.closeContainer(props.botId, active.value.container_id).catch(() => {}) }
  active.value = null
  items.value = new Map()
})

/** 常驻面板查询：当前是否有已打开的容器窗口（GUI / 附加箱子） */
async function syncCurrentWindow() {
  try {
    const { data } = await botApi.currentWindow(props.botId)
    if (!data?.opened || !data.container_id) return
    pushStack(data.container_id)
    active.value = {
      container_id: data.container_id,
      block_name: data.block_name || '容器',
      slot_count: data.slot_count || 27,
      position: { x: 0, y: 0, z: 0 },
    }
    const m = new Map<number, ChestSlot>()
    for (const it of (data.items || [])) {
      const slot = typeof it.slot === 'number' ? it.slot : it.slot_index
      if (slot == null) continue
      m.set(slot, {
        item_id: it.item_id || it.name || '',
        name: it.name || it.display_name || '',
        item_name_zh: it.item_name_zh || it.display_name_zh || '',
        count: it.count || 0,
        custom_name: it.custom_name || null,
        lore: it.lore || [],
      })
    }
    items.value = m
  } catch { /* 忽略：无窗口/未连接时静默 */ }
}

/** 全局事件兜底：InventoryGrid 激活手持物品成功后通知切换（不依赖 socket 时序） */
function onGuiOpened(e: Event) {
  const d = (e as CustomEvent).detail
  if (!d || d.bot_id !== props.botId || !d.container_id) return
  pushStack(d.container_id)
  active.value = {
    container_id: d.container_id,
    block_name: d.block_name || '容器',
    slot_count: d.slot_count || 27,
    position: { x: 0, y: 0, z: 0 },
  }
  items.value = new Map()
  holding.value = false
  holdingSlot.value = -1
  refreshSnapshot()
}

function getSlot(idx: number) { return items.value.get(idx) || null }
function slotTip(idx: number) {
  const s = getSlot(idx)
  if (!s) return '空'
  const nm = s.custom_name || s.item_name_zh || s.name || s.item_id
  return `${nm} ×${s.count}`
}
function showDetail(idx: number) {
  const s = getSlot(idx)
  if (!s) return
  detail.value = { show: true, item: s, idx }
}

// ── 窗口点击（2026-08-12）：左键=拿/放整组 右键=拿/放半组 ──
async function doClick(idx: number, mouseButton: 0 | 1) {
  if (!active.value || clicking.value) return
  clicking.value = true
  try {
    const { data } = await botApi.inventoryClick(props.botId, {
      target: 'container',
      slot: idx,
      mouse_button: mouseButton,
      container_id: active.value.container_id,
    })
    const r = data?.result || {}
    holding.value = !!r.holding
    holdingSlot.value = r.holding ? idx : -1
    // 服务器打开了新容器窗口（快捷潜影盒 GUI）→ 自动切换
    if (r.new_container_id) {
      active.value = {
        container_id: r.new_container_id,
        block_name: r.block_name || '潜影盒',
        slot_count: r.slot_count || 27,
        position: { x: 0, y: 0, z: 0 },
      }
      items.value = new Map()
      ElMessage.success('已打开新容器窗口')
    }
    await refreshSnapshot()
  } catch (e: any) {
    ElMessage.error(errMsg(e, '窗口点击失败'))
  } finally {
    clicking.value = false
  }
}

/** 左键：空手持且槽位有物品 → 详情（弹窗内可拿起）；手持 → 放下 */
async function onSlotClick(idx: number) {
  if (clicking.value) return
  if (holding.value) {
    await doClick(idx, 0)
    return
  }
  showDetail(idx)
}

/** 右键：拿/放半组（快捷潜影盒：右键容器内潜影盒物品可触发服务器开新窗） */
async function onSlotRight(idx: number) {
  await doClick(idx, 1)
}

/** 详情弹窗内「拿起」（左键窗口点击） */
async function doPickup() {
  if (detail.value.idx < 0) return
  const idx = detail.value.idx
  detail.value.show = false
  await doClick(idx, 0)
}

/** 丢弃到虚空（手持时）：点击 -999 槽（窗口外） */
async function doDropToVoid() {
  if (!active.value || clicking.value) return
  clicking.value = true
  try {
    await botApi.inventoryClick(props.botId, {
      target: 'container', slot: -999, mouse_button: 0, container_id: active.value.container_id,
    })
    holding.value = false
    holdingSlot.value = -1
    ElMessage.success('已丢弃到虚空')
    await refreshSnapshot()
  } catch (e: any) {
    ElMessage.error(errMsg(e, '丢弃失败'))
  } finally {
    clicking.value = false
  }
}

// ── socket：服务器自动打开/关闭容器窗口（快捷潜影盒等） → 切换面板 ──
function onContainerOpened(payload: any) {
  if (!payload || payload.bot_id !== props.botId || !payload.container_id) return
  pushStack(payload.container_id)
  active.value = {
    container_id: payload.container_id,
    block_name: payload.block_name || '容器',
    slot_count: payload.slot_count || 27,
    position: { x: 0, y: 0, z: 0 },
  }
  items.value = new Map()
  holding.value = false
  holdingSlot.value = -1
  refreshSnapshot()
}
function onContainerClosed(payload: any) {
  if (!payload) return
  popStack(payload.container_id)
  if (active.value && active.value.container_id === payload.container_id) {
    active.value = null
    items.value = new Map()
    holding.value = false
    holdingSlot.value = -1
  }
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
    ElMessage.error(errMsg(err, '扫描失败'))
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
    pushStack(d.container_id)
    items.value = new Map()
    await refreshSnapshot()
  } catch (err: any) {
    ElMessage.error(errMsg(err, '打开失败（可能被阻挡/无法交互）'))
  } finally {
    busy.value = false
  }
}

function pushStack(cid: string) {
  if (!stack.value.includes(cid)) stack.value.push(cid)
}
function popStack(cid: string) {
  stack.value = stack.value.filter(x => x !== cid)
}

/** 右键方块（箱子 UI / 快捷潜影盒触发）：服务器插件弹出 GUI → 自动切换容器面板 */
async function goActivate(c: ContainerBlock) {
  if (activating.value) return
  activating.value = true
  try {
    const { data } = await botApi.inventoryActivateBlock(props.botId, { x: c.x, y: c.y, z: c.z })
    const r = data?.result || {}
    if (r.opened || r.new_container_id) {
      ElMessage.success('已打开新窗口，正在读取容器…')
      // 若响应已带新容器 id（事件可能稍晚），直接切换兜底
      if (r.new_container_id) {
        pushStack(r.new_container_id)
        active.value = { container_id: r.new_container_id, block_name: r.block_name || zhBlock(c.name), slot_count: r.slot_count || 27, position: { x: c.x, y: c.y, z: c.z } }
        items.value = new Map()
        await refreshSnapshot()
      }
    } else {
      const cw = r.current_window
      ElMessage.warning(cw
        ? `当前打开窗口：${cw.type}（${cw.title || '无标题'}）——若该窗口在面板未显示，请用下方「附加箱子」列表的「右键」按钮`
        : '未检测到打开的窗口（该方块/物品未触发 GUI，或服务器插件无响应）')
    }
  } catch (e: any) {
    ElMessage.error(errMsg(e, '右键方块失败'))
  } finally {
    activating.value = false
  }
}

/** 返回上一层：关闭当前窗口，服务器会重开父窗口（windowOpen → mf_container_opened 自动切换） */
async function goBack() {
  if (!active.value || clicking.value) return
  const cur = active.value.container_id
  popStack(cur)
  try {
    await botApi.closeContainer(props.botId, cur)
  } catch { /* 忽略 */ }
  active.value = null
  items.value = new Map()
  holding.value = false
  holdingSlot.value = -1
  ElMessage.info('已关闭当前窗口，等待返回上一层容器…')
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
        custom_name: it.custom_name || null,
        lore: it.lore || [],
      })
    }
    items.value = m
    // 槽位数以快照为准（大箱子 54 / 小箱子 27）
    if (resp.data?.slot_count) active.value.slot_count = resp.data.slot_count
  } catch (err: any) {
    ElMessage.error(errMsg(err, '读取容器失败'))
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
  holding.value = false
  holdingSlot.value = -1
  stack.value = []
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
  grid-template-columns: repeat(9, var(--slot, 42px));
  gap: 3px;
  justify-content: flex-start;
}
.chest-grid.half { grid-template-rows: repeat(3, var(--slot, 42px)); overflow: hidden; }
/* 槽位走 CSS 变量 + 主题 Token：原 #141414 纯黑/冷灰在暖墨主题下发冷发脏 */
.slot {
  width: var(--slot, 42px); height: var(--slot, 42px);
  border: 2px solid var(--border-strong); border-radius: 3px;
  background: var(--bg-elevated); cursor: pointer; position: relative;
}
.slot:hover { border-color: var(--text-muted); }
.slot.filled { background: var(--bg-active); }
.slot .count {
  position: absolute; right: 2px; bottom: 1px; font-size: 10px; color: var(--text-primary);
  text-shadow: 1px 1px 0 rgba(0,0,0,0.6); font-family: var(--font-mono);
}
.chest-empty { color: var(--text-muted); font-size: 12px; padding: 12px 0; text-align: center; border: 1px dashed var(--border-default); border-radius: var(--radius-md); }
.detail-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--border-default); }
.detail-row:last-child { border-bottom: none; }
.custom-name { color: var(--warning); font-weight: 600; }
.lore-row { align-items: flex-start; }
.lore-list { display: flex; flex-direction: column; gap: 2px; text-align: right; }
.lore-line { color: var(--text-secondary); font-size: 12px; font-style: italic; }
.detail-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }

/* 窗口点击提示 + 手持高亮（2026-08-12） */
.click-hint { display: flex; align-items: center; gap: 10px; font-size: 11px; color: var(--text-muted); margin-bottom: 6px; flex-wrap: wrap; }
.click-hint span.holding { color: var(--accent); font-weight: 600; }
.click-hint .holding-text { color: var(--warning); font-weight: 600; }
.slot.holding { border-color: var(--warning); box-shadow: 0 0 4px var(--warning-bg); }
.window-chain { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }

/* ============ 窄屏适配 ============
   9 列固定 42px + 8×3px 间距 = 402px，在 360–390px 手机抽屉内（可用约 295px）
   会横向溢出被裁切。改用 CSS 变量按视口收缩，保证 9 列完整可见。 */
@media (max-width: 768px) {
  .container-panel { --slot: clamp(26px, calc((100vw - 150px) / 9), 42px); }
  .chest-grid { gap: 2px; }
  .slot .count { font-size: 9px; right: 1px; bottom: 0; }
  .chest-head { gap: 8px; }
  .container-row { gap: 6px; padding: 5px 6px; }
  .cname { min-width: 56px; font-size: 12px; }
  .cdist { min-width: 40px; }
}
</style>
