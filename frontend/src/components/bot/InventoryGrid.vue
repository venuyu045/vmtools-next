<template>
  <div class="inv-container">
    <div v-if="moveMode" class="cursor-bar move">📦 移动模式：点击要移动的物品（高亮），再点击目标槽位完成移动/交换 · 点击原槽位/ESC 取消</div>
    <div v-else-if="cursorMsg" class="cursor-bar">{{ cursorMsg }}</div>
    <div class="help">{{ p.clickable ? '左键=拿/放/交换 · 右键=丢弃 · 🔄刷新看结果' : '点击物品=详情（左键拿/放·右键半组·手持·移动·丢弃·使用）· 右键槽位=半组' }}</div>

    <div class="layout">
      <!-- Main inventory: slots 9-35 (3 rows), with armor/offhand on right -->
      <div class="main-area">
        <div class="inv-rows">
          <div v-for="row in 3" :key="row" class="inv-row">
            <div v-for="col in 9" :key="9+(row-1)*9+col-1"
              class="slot" :class="slotCls(9+(row-1)*9+col-1)"
              :title="tip(9+(row-1)*9+col-1)"
              @click.left="onSlotClick(9+(row-1)*9+col-1)"
              @click.right.prevent="onSlotRight(9+(row-1)*9+col-1, $event)"
            >
              <ItemIcon v-if="get(9+(row-1)*9+col-1)" :item-id="get(9+(row-1)*9+col-1)!.item_id" :name="get(9+(row-1)*9+col-1)!.item_name_zh || label(get(9+(row-1)*9+col-1)!.item_id)" :size="32" class="icon" />
              <span v-if="get(9+(row-1)*9+col-1)" class="count">{{ get(9+(row-1)*9+col-1)!.count }}</span>
            </div>
          </div>
        </div>

        <!-- Hotbar: slots 0-8 -->
        <div class="hotbar-row">
          <div v-for="i in 9" :key="'h'+i"
            class="slot" :class="[slotCls(i-1), { sel: (i-1) === (inventory?.selected_hotbar ?? 0) }]"
            :title="tip(i-1)"
            @click.left="onSlotClick(i-1)"
            @click.right.prevent="onSlotRight(i-1, $event)"
          >
            <ItemIcon v-if="get(i-1)" :item-id="get(i-1)!.item_id" :name="get(i-1)!.item_name_zh || label(get(i-1)!.item_id)" :size="32" class="icon" />
            <span v-if="get(i-1)" class="count">{{ get(i-1)!.count }}</span>
            <span class="num">{{ i }}</span>
          </div>
        </div>
      </div>

      <!-- Armor 36-39 + Offhand 40 + Crafting 41-44 -->
      <div class="side-area">
        <div class="side-label">护甲</div>
        <div v-for="(armor, i) in ['头','胸','腿','脚','副']" :key="'a'+i"
          class="slot" :class="slotCls(36+i)"
          :title="armor + ': ' + tip(36+i)"
          @click.left="onSlotClick(36+i)"
          @click.right.prevent="onSlotRight(36+i, $event)"
        >
          <ItemIcon v-if="get(36+i)" :item-id="get(36+i)!.item_id" :name="get(36+i)!.item_name_zh || label(get(36+i)!.item_id)" :size="32" class="icon" />
          <span v-if="get(36+i)" class="count">{{ get(36+i)!.count }}</span>
          <span class="num">{{ armor }}</span>
        </div>
        <div class="side-label" style="margin-top:8px">合成</div>
        <div class="craft-grid">
          <div v-for="(s, i) in [41,42,43,44,45]" :key="'c'+s"
            class="slot" :class="[slotCls(s), { out: s === 45 }]"
            :title="(s===45?'输出':'合成') + ': ' + tip(s)"
            @click.left="onSlotClick(s)"
            @click.right.prevent="onSlotRight(s, $event)"
          >
            <ItemIcon v-if="get(s)" :item-id="get(s)!.item_id" :name="get(s)!.item_name_zh || label(get(s)!.item_id)" :size="32" class="icon" />
            <span v-if="get(s)" class="count">{{ get(s)!.count }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="bar">
      <el-button size="small" @click="doRefresh" :loading="loading">🔄 刷新</el-button>
      <template v-if="!p.clickable">
        <el-button size="small" :type="moveMode ? 'warning' : 'default'" @click="toggleMoveMode">📦 {{ moveMode ? '退出移动' : '移动物品' }}</el-button>
        <el-button size="small" @click="openDropDlg" :disabled="!hasItems">🗑 丢弃物品</el-button>
      </template>
      <span>{{ inventory?.total_items ?? 0 }} 物品 · {{ inventory?.empty_slots ?? 0 }} 空位</span>
      <span v-if="!p.clickable && inventory?.selected_hotbar != null" class="held-info">✋ 手持：快捷栏 {{ (inventory.selected_hotbar ?? 0) + 1 }}</span>
    </div>

    <!-- 物品详情弹窗（MF 模式） -->
    <el-dialog v-model="detail.show" :title="'物品详情'" width="420px" append-to-body>
      <div v-if="detail.item" class="detail-body">
          <div class="detail-head">
          <ItemIcon :item-id="detail.item.item_id" :name="detail.item.item_name_zh || label(detail.item.item_id)" :size="52" class="detail-icon" />
          <div class="detail-titles">
            <div class="detail-name">{{ detail.item.item_name_zh || label(detail.item.item_id) }}</div>
            <div v-if="detail.item.custom_name" class="detail-custom">{{ detail.item.custom_name }}</div>
            <div class="detail-id mono">{{ detail.item.item_id }}</div>
          </div>
        </div>

        <el-descriptions :column="1" size="small" border class="detail-desc">
          <el-descriptions-item v-if="detail.item.custom_name" label="命名"><span class="ench-name">{{ detail.item.custom_name }}</span></el-descriptions-item>
          <el-descriptions-item v-if="detail.item.lore && detail.item.lore.length" label="描述">
            <div v-for="(l, i) in detail.item.lore" :key="i" class="lore-line">{{ l }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="数量">{{ detail.item.count }}</el-descriptions-item>
          <el-descriptions-item label="槽位">{{ slotLabel(detail.item.slot) }}</el-descriptions-item>
          <el-descriptions-item label="堆叠上限">{{ detail.item.max_stack }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.item.durability != null && detail.item.max_durability" label="耐久">
            {{ detail.item.durability }} / {{ detail.item.max_durability }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.item.enchantments && detail.item.enchantments.length" label="附魔">
            <div v-for="(e, i) in detail.item.enchantments" :key="i" class="ench">{{ enchLabel(e) }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <div class="detail-actions">
          <el-button v-if="isHotbarSlot(detail.item.slot)" size="small" type="primary" @click="doHold">✋ 设为手持</el-button>
          <el-button size="small" type="primary" plain @click="doInvPickup">左键拿起/放下</el-button>
          <el-button size="small" plain @click="doInvHalf">右键半组</el-button>
          <el-button size="small" @click="doActivateHeld">右键激活（手持）</el-button>
          <el-button size="small" @click="doMoveFromDetail">📦 移动</el-button>
          <el-button size="small" type="warning" @click="doUse">🍖 使用</el-button>
          <el-button size="small" @click="doDropOne">丢 1 个</el-button>
          <el-button size="small" type="danger" @click="doDropStack">丢整组 ({{ detail.item.count }})</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 丢弃物品弹窗（MF 模式：显式按钮，非右键） -->
    <el-dialog v-model="dropDlg.show" title="丢弃物品" width="380px" append-to-body>
      <el-form label-width="70px" @submit.prevent>
        <el-form-item label="物品">
          <el-select v-model="dropDlg.itemType" placeholder="选择要丢弃的物品" style="width:100%">
            <el-option v-for="s in distinctItems" :key="s.item_id" :label="`${s.item_name_zh || label(s.item_id)} × ${s.count}`" :value="s.item_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="dropDlg.count" :min="1" :max="dropDlg.maxCount" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dropDlg.show = false">取消</el-button>
        <el-button type="danger" :disabled="!dropDlg.itemType" @click="doDropAll">丢弃</el-button>
      </template>
    </el-dialog>

    <!-- Context menu (MCC mode only) -->
    <div v-if="menu.show" class="ctx" :style="{top:menu.y+'px',left:menu.x+'px'}">
      <div class="ctxh">{{ label(menu.item?.item_id||'') }} ×{{ menu.item?.count }}</div>
      <div class="ctxi" @click="doDrop('DropItemStack')">🗑 丢弃整组</div>
      <div class="ctxi" @click="doDrop('DropSingleItem')">🗑 丢弃 1 个</div>
      <div class="ctxi cancel" @click="menu.show=false">取消</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import ItemIcon from '@/components/ItemIcon.vue'
import { botApi } from '@/api/bot'

interface Slot {
  slot: number
  item_id: string
  display_name: string
  item_name_zh?: string
  count: number
  max_stack?: number
  durability?: number | null
  max_durability?: number | null
  enchantments?: Array<{ name: string; lvl: number }>
  custom_name?: string | null
  lore?: string[]
}
interface Data { bot_id: string; inventory_id: number; slots: Slot[]; hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number }

const p = defineProps<{ botId: string; inventory: Data | null; loading: boolean; clickable?: boolean }>()
const emit = defineEmits<{
  refresh: []
  action: [p: { action: string; slot_id: number }]
  drop: [p: { item_type: string; count: number; slot?: number }]
  selectHotbar: [slot: number]
  move: [p: { slot_id: number; dest_slot_id: number }]
  use: [p: { item_type: string; slot: number }]
}>()

const cursorSlot = ref(-1)
const cursorText = ref('')
const menu = ref({ show: false, x: 0, y: 0, item: null as Slot | null, slot_id: 0 })
// MF 移动模式状态
const moveMode = ref(false)
const moveFrom = ref(-1)
// 详情 / 丢弃弹窗
const detail = ref({ show: false, item: null as Slot | null })
const dropDlg = ref({ show: false, itemType: '', count: 1, maxCount: 64 })

const cursorMsg = computed(() => cursorSlot.value >= 0 ? `👆 已从槽位 ${cursorSlot.value} 拿起物品，再点目标格放下/交换` : '')

const sm = computed(() => {
  const m: Record<number, Slot> = {}
  for (const s of p.inventory?.slots || []) m[s.slot] = s
  return m
})
function get(i: number): Slot | undefined { return sm.value[i] }

const hasItems = computed(() => (p.inventory?.slots?.length || 0) > 0)

/** 去重物品（按 item_id 聚合数量），供「丢弃物品」弹窗选择 */
const distinctItems = computed(() => {
  const map = new Map<string, Slot>()
  for (const s of p.inventory?.slots || []) {
    const cur = map.get(s.item_id)
    if (cur) { cur.count += s.count; continue }
    map.set(s.item_id, { ...s })
  }
  return Array.from(map.values())
})

function label(id: string): string {
  return (id || '').replace('minecraft:', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function tip(i: number): string {
  const s = get(i)
  if (s) return `${s.item_name_zh || label(s.item_id)} ×${s.count}`
  return `空`
}

function slotCls(i: number) {
  return {
    filled: !!get(i),
    cursor: cursorSlot.value === i,
    moveFrom: moveMode.value && moveFrom.value === i,
  }
}

/** 前端标准槽位 → 中文位置标签 */
function slotLabel(slot: number): string {
  if (slot >= 0 && slot <= 8) return `快捷栏 ${slot + 1}`
  if (slot >= 9 && slot <= 35) return `背包 ${slot - 8}`
  if (slot === 36) return '头盔'
  if (slot === 37) return '胸甲'
  if (slot === 38) return '护腿'
  if (slot === 39) return '靴子'
  if (slot === 40) return '副手'
  if (slot === 45) return '合成输出'
  if (slot >= 41 && slot <= 44) return `合成 ${slot - 40}`
  return `槽位 ${slot}`
}

function isHotbarSlot(slot: number): boolean {
  return slot >= 0 && slot <= 8
}

function enchLabel(e: { name: string; lvl: number }): string {
  const name = e.name ? e.name.replace(/_/g, ' ') : '附魔'
  return `${name} ${toRoman(e.lvl || 1)}`
}

function toRoman(n: number): string {
  const table: Array<[number, string]> = [[10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']]
  let v = Math.max(1, Math.min(10, Math.round(n)))
  let out = ''
  for (const [num, sym] of table) { while (v >= num) { out += sym; v -= num } }
  return out
}

/** 槽位点击统一入口：MF 模式（clickable=false）与 MCC 模式（clickable=true）分派 */
async function onSlotClick(slotIdx: number) {
  menu.value.show = false

  // 移动模式：源 → 目标（连续移动，不移除 moveMode——再点按钮/ESC 才退出）
  if (moveMode.value) {
    if (moveFrom.value === -1) {
      if (!get(slotIdx)) return
      moveFrom.value = slotIdx
      return
    }
    if (moveFrom.value === slotIdx) { moveFrom.value = -1; return }
    const from = moveFrom.value
    moveFrom.value = -1
    emit('move', { slot_id: from, dest_slot_id: slotIdx })
    return
  }

  // MF 模式：单击任意槽位（含快捷栏）→ 打开物品详情（详情内可设为手持/移动/丢弃）
  // 统一入口避免「快捷栏点击=手持」与「移动/丢弃」的交互冲突
  if (p.clickable === false) {
    const s = get(slotIdx)
    if (s) detail.value = { show: true, item: s }
    return
  }

  // MCC 模式：原窗口点击逻辑（拿/放/交换）
  if (cursorSlot.value >= 0 && cursorSlot.value === slotIdx) {
    cursorSlot.value = -1
    return
  }
  emit('action', { action: 'LeftClick', slot_id: slotIdx })
  if (cursorSlot.value === -1 && get(slotIdx)) {
    cursorSlot.value = slotIdx
  } else {
    cursorSlot.value = -1
    setTimeout(doRefresh, 300)
  }
}

/** 右键：MF 模式=窗口点击右键（拿/放半组）；MCC 模式弹丢弃菜单 */
function onSlotRight(slotIdx: number, e: MouseEvent) {
  if (p.clickable === false) {
    doInvClick(slotIdx, 1)  // MF：窗口点击右键（拿/放半组）
    return
  }
  const s = get(slotIdx)
  if (!s) return
  menu.value = { show: true, x: Math.min(e.clientX, innerWidth - 140), y: Math.min(e.clientY, innerHeight - 160), item: s, slot_id: slotIdx }
}

// ── 窗口点击（2026-08-12）：左键=拿/放整组 右键=拿/放半组（快捷潜影盒等） ──
async function doInvClick(slotIdx: number, mouseButton: 0 | 1) {
  try {
    const { data } = await botApi.inventoryClick(p.botId, {
      target: 'inventory',
      slot: slotIdx,
      mouse_button: mouseButton,
    })
    const r = data?.result || {}
    if (r.holding) {
      ElMessage.info('已拿起物品：点击目标槽放下 / 再右键半组 / 弹窗内操作')
    }
    if (r.new_container_id) {
      ElMessage.success('已打开新容器窗口，请到下方「附加箱子」面板查看')
    }
    emit('refresh')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '窗口点击失败')
  }
}

/** 详情弹窗：左键拿起/放下 */
async function doInvPickup() {
  if (!detail.value.item) return
  const slot = detail.value.item.slot
  detail.value.show = false
  await doInvClick(slot, 0)
}

/** 详情弹窗：右键半组 */
async function doInvHalf() {
  if (!detail.value.item) return
  const slot = detail.value.item.slot
  detail.value.show = false
  await doInvClick(slot, 1)
}

/** 右键激活手持物品（快捷潜影盒等）：先「设为手持」再激活 */
async function doActivateHeld() {
  detail.value.show = false
  try {
    const { data } = await botApi.inventoryActivateItem(p.botId)
    const r = data?.result || {}
    if (r.opened || r.new_container_id) {
      ElMessage.success('已打开新容器窗口，正在读取…')
      // 全局事件兜底：直接通知下方 ContainerPanel 切换（不依赖 socket 时序）
      window.dispatchEvent(new CustomEvent('vmt:gui-opened', {
        detail: {
          bot_id: p.botId,
          container_id: r.new_container_id || null,
          block_name: r.current_window?.title || '箱子 UI',
          slot_count: r.current_window?.slot_count || 27,
        },
      }))
    } else {
      const cw = r.current_window
      ElMessage.warning(cw
        ? `当前打开窗口：${cw.type}（${cw.title || '无标题'}）——若面板未显示，请用下方「附加箱子」列表的「右键」按钮触发`
        : '未检测到打开的窗口；若为箱子 UI，请用下方「附加箱子」列表的「右键」按钮触发')
    }
    emit('refresh')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '激活失败')
  }
}

// ── 移动模式 ──
function toggleMoveMode() {
  moveMode.value = !moveMode.value
  if (!moveMode.value) moveFrom.value = -1
  else cursorSlot.value = -1
}

function doMoveFromDetail() {
  if (!detail.value.item) return
  moveFrom.value = detail.value.item.slot
  moveMode.value = true
  detail.value.show = false
  ElMessage.success(`已选择「${detail.value.item.item_name_zh || label(detail.value.item.item_id)}」，点击目标槽位移动`)
}

// ── 手持 ──
function doHold() {
  if (!detail.value.item) return
  const slot = detail.value.item.slot
  detail.value.show = false
  emit('selectHotbar', slot)
}

// ── 使用物品（吃食物等） ──
function doUse() {
  if (!detail.value.item) return
  const it = detail.value.item
  detail.value.show = false
  emit('use', { item_type: it.item_id, slot: it.slot })
}

// ── 丢弃（按钮） ──
function doDropOne() {
  if (!detail.value.item) return
  const it = detail.value.item
  detail.value.show = false
  // 精确槽位丢弃：传 slot，避免按类型全局找第一个槽位丢错
  emit('drop', { item_type: it.item_id, count: 1, slot: it.slot })
}

function doDropStack() {
  if (!detail.value.item) return
  const it = detail.value.item
  detail.value.show = false
  emit('drop', { item_type: it.item_id, count: it.count, slot: it.slot })
}

function openDropDlg() {
  dropDlg.value.show = true
  dropDlg.value.itemType = ''
  dropDlg.value.count = 1
  dropDlg.value.maxCount = 64
}

function doDropAll() {
  if (!dropDlg.value.itemType) return
  const it = dropDlg.value.itemType
  const cnt = Math.max(1, Math.floor(dropDlg.value.count || 1))
  dropDlg.value.show = false
  // 批量丢弃：不指定 slot，按类型全局凑足数量（语义正确）
  emit('drop', { item_type: it, count: cnt })
}

// ── MCC 右键菜单丢弃（保留） ──
function doDrop(a: string) {
  if (!menu.value.item) return
  menu.value.show = false
  emit('drop', { item_type: menu.value.item.item_id, count: a === 'DropItemStack' ? 64 : 1 })
}

function doRefresh() { cursorSlot.value = -1; emit('refresh') }

// Esc to cancel
onMounted(() => {
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { cursorSlot.value = -1; moveFrom.value = -1 } })
  document.addEventListener('click', () => menu.value.show = false)
})
</script>

<style scoped>
.inv-container { padding: 8px; user-select: none; }
.cursor-bar { text-align: center; padding: 5px 8px; margin-bottom: 6px; background: rgba(255,165,0,0.12); color: #ffa500; font-size: 12px; border-radius: 4px; }
.cursor-bar.move { background: rgba(64,158,255,0.12); color: #409eff; }
.help { text-align: center; font-size: 11px; color: #777; padding: 4px 0 8px; }

.layout { display: flex; gap: 8px; justify-content: center; align-items: flex-start; }

.main-area { display: flex; flex-direction: column; align-items: center; }
.inv-rows { display: flex; flex-direction: column; gap: 2px; }
.inv-row { display: flex; gap: 2px; }
.hotbar-row { display: flex; gap: 2px; margin-top: 6px; }

.side-area { display: flex; flex-direction: column; gap: 2px; }
.side-label { font-size: 10px; color: #666; text-align: center; padding: 2px; }
.craft-grid {
  display: grid; grid-template-columns: repeat(2, 42px); gap: 2px; justify-content: center;
}
.slot.out { border-color: #666; }

.slot {
  width: 42px; height: 42px; border: 2px solid #3a3a3a; border-radius: 3px;
  background: #141414; cursor: pointer; position: relative; transition: border-color 0.1s;
}
.slot:hover { border-color: #aaa; }
.slot.filled { background: #1a1a1a; }
.slot.sel { border-color: #ffe082; box-shadow: 0 0 4px rgba(255,224,130,0.4); }
.slot.cursor { border-color: #ff8c00; border-style: dashed; background: rgba(255,140,0,0.08); }
.slot.moveFrom { border-color: #409eff; border-style: dashed; background: rgba(64,158,255,0.15); }
.slot .icon { position: absolute; width: 32px; height: 32px; top: 4px; left: 4px; image-rendering: pixelated; }
.slot .count { position: absolute; bottom: 1px; right: 3px; font-size: 11px; color: #fff; font-weight: bold; text-shadow: 0 0 3px #000; }
.slot .num { position: absolute; top: 0; left: 2px; font-size: 9px; color: #888; }

.bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; justify-content: center; font-size: 12px; color: #aaa; flex-wrap: wrap; }
.held-info { color: var(--text-secondary, #bbb); font-size: 12px; }

.ctx { position: fixed; z-index: 9999; background: #2a2a2a; border: 1px solid #555; border-radius: 5px; padding: 4px 0; min-width: 140px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
.ctxh { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; }
.ctxi { padding: 7px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.ctxi:hover { background: #444; }
.ctxi.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }

/* 详情弹窗 */
.detail-body { display: flex; flex-direction: column; gap: 14px; }
.detail-head { display: flex; align-items: center; gap: 14px; }
.detail-icon { image-rendering: pixelated; }
.detail-name { font-size: 17px; font-weight: 600; color: var(--text-primary, #fff); }
.detail-custom { font-size: 14px; color: #e6a23c; font-weight: 600; margin-top: 2px; }
.detail-id { font-size: 12px; color: var(--text-muted, #888); margin-top: 2px; }
.ench-name { color: #e6a23c; font-weight: 600; }
.lore-line { color: #b48cff; font-size: 12px; font-style: italic; line-height: 1.5; }
.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.ench { font-size: 13px; color: #b48cff; }
</style>
