<template>
  <div class="inventory-grid">
    <div v-if="!inventory" class="empty-state">点击 🔄 刷新 加载背包数据</div>
    <div v-else>
      <!-- Cursor item overlay -->
      <div v-if="cursorSlot !== -1" class="cursor-hint">
        已选中槽位 {{ cursorSlot }} · 再点目标格子交换 · Esc 取消
      </div>

      <!-- Main inventory (slots 0-35) -->
      <div class="section-title">背包</div>
      <div class="main-rows">
        <div v-for="row in 4" :key="row" class="inv-row">
          <div
            v-for="col in 9" :key="(row-1)*9+col-1" class="grid-slot"
            :class="slotClass((row-1)*9+col-1)"
            :title="slotTitle((row-1)*9+col-1)"
            @click.left="onSlotClick((row-1)*9+col-1)"
            @click.right.prevent="onSlotRight((row-1)*9+col-1, $event)"
          >
            <SlotContent :slot-data="getSlot((row-1)*9+col-1)" />
            <span class="slot-idx">{{ (row-1)*9+col-1 }}</span>
          </div>
        </div>
      </div>

      <!-- Hotbar (slots 36-44) -->
      <div class="section-title">快捷栏</div>
      <div class="hotbar-row">
        <div
          v-for="i in 9" :key="'h'+i" class="grid-slot"
          :class="[slotClass(35 + i), { selected: (i - 1) === (inventory?.selected_hotbar ?? 0) }]"
          :title="slotTitle(35 + i)"
          @click.left="onSlotClick(35 + i)"
          @click.right.prevent="onSlotRight(35 + i, $event)"
        >
          <SlotContent :slot-data="getSlot(35 + i)" />
          <span class="slot-num">{{ i }}</span>
        </div>
      </div>

      <!-- Stats -->
      <div class="stats-bar">
        <el-button size="small" @click="$emit('refresh')" :loading="loading">🔄 刷新</el-button>
        <span>物品 {{ inventory?.total_items }} · 空位 {{ inventory?.empty_slots }}</span>
      </div>
    </div>

    <!-- Right-click menu -->
    <div v-if="ctx.show" class="context-menu" :style="{ top: ctx.y + 'px', left: ctx.x + 'px' }">
      <div class="menu-header">{{ formatName(ctx.item?.item_id || '') }} ×{{ ctx.item?.count }}</div>
      <div class="menu-item" @click="ctxDrop('DropItemStack')">🗑 丢弃整组</div>
      <div class="menu-item" @click="ctxDrop('DropSingleItem')">🗑 丢弃一个</div>
      <div class="menu-item" @click="ctxSwap">🔀 移到快捷栏</div>
      <div class="menu-item cancel" @click="ctx.show = false">取消</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, defineComponent, h } from 'vue'

interface InvSlot { slot: number; item_id: string; display_name: string; count: number }
interface InvData {
  bot_id: string; inventory_id: number; slots: InvSlot[]
  hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number
}

const props = defineProps<{ botId: string; inventory: InvData | null; loading: boolean }>()
const emit = defineEmits<{ refresh: []; action: [payload: { action: string; slot_id: number; inventory_id?: number }]; drop: [payload: { item_type: string; count: number }] }>()

const cursorSlot = ref(-1)
const ctx = ref({ show: false, x: 0, y: 0, item: null as InvSlot | null, slot_id: 0 })

const slotMap = computed(() => {
  const m: Record<number, InvSlot> = {}
  for (const s of props.inventory?.slots || []) m[s.slot] = s
  return m
})

function getSlot(idx: number): InvSlot | undefined { return slotMap.value[idx] }

function slotClass(idx: number) {
  return {
    'has-item': !!getSlot(idx),
    'empty-slot': !getSlot(idx),
    'cursor-pick': idx === cursorSlot.value,
  }
}

function slotTitle(idx: number): string {
  const s = getSlot(idx)
  if (cursorSlot.value !== -1 && !s) return '放这里'
  return s ? `${formatName(s.item_id)} ×${s.count}` : '空'
}

function formatName(id: string): string {
  return (id || '').replace('minecraft:', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// Slot content renderer
const itemColors: Record<string, string> = {
  shulkerbox: '#b366cc', playerhead: '#cc6633', hopper: '#666666',
  stick: '#8B6914', azalea: '#558833', floweringazalea: '#cc3388',
}

function itemBg(id: string): string {
  const lower = id.toLowerCase().replace('minecraft:', '')
  for (const [k, v] of Object.entries(itemColors)) if (lower.includes(k)) return v
  const h = id.split('').reduce((v, c) => v * 31 + c.charCodeAt(0), 0)
  return `hsl(${Math.abs(h) % 360}, 50%, 42%)`
}

const SlotContent = defineComponent({
  props: { slotData: Object as () => InvSlot | undefined },
  setup(p) {
    return () => {
      if (!p.slotData) return null
      const id = p.slotData.item_id
      const name = id.replace('minecraft:', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
      const short = name.length > 9 ? name.slice(0, 8) + '…' : name
      return h('div', { class: 'item-inner', style: { background: itemBg(id) } }, [
        h('span', { class: 'item-name' }, short),
        h('span', { class: 'item-count' }, p.slotData.count > 1 ? String(p.slotData.count) : ''),
      ])
    }
  },
})

// Click handlers
function onSlotClick(slotIdx: number) {
  ctx.value.show = false
  const has = getSlot(slotIdx)

  if (cursorSlot.value === -1) {
    // Pick up
    if (has) cursorSlot.value = slotIdx
  } else if (cursorSlot.value === slotIdx) {
    // Click same slot → cancel
    cursorSlot.value = -1
  } else {
    // Swap: send two LeftClicks
    emit('action', { action: 'LeftClick', slot_id: cursorSlot.value, inventory_id: 0 })
    emit('action', { action: 'LeftClick', slot_id: slotIdx, inventory_id: 0 })
    cursorSlot.value = -1
    setTimeout(() => emit('refresh'), 200)
  }
}

function onSlotRight(slotIdx: number, e: MouseEvent) {
  const s = getSlot(slotIdx)
  if (!s) return
  ctx.value = { show: true, x: Math.min(e.clientX, window.innerWidth - 150), y: Math.min(e.clientY, window.innerHeight - 200), item: s, slot_id: slotIdx }
}

function ctxDrop(action: string) {
  if (!ctx.value.item) return
  ctx.value.show = false
  emit('drop', { item_type: ctx.value.item.item_id, count: action === 'DropItemStack' ? 64 : 1 })
}

function ctxSwap() {
  if (!ctx.value.item) return
  ctx.value.show = false
  // Move to first empty hotbar slot (36-44)
  const emptyHotbar = [36, 37, 38, 39, 40, 41, 42, 43, 44].find(i => !getSlot(i))
  if (emptyHotbar != null) {
    emit('action', { action: 'LeftClick', slot_id: ctx.value.slot_id, inventory_id: 0 })
    emit('action', { action: 'LeftClick', slot_id: emptyHotbar, inventory_id: 0 })
    setTimeout(() => emit('refresh'), 200)
  }
}

function cancelPick() { cursorSlot.value = -1; ctx.value.show = false }

onMounted(() => {
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') cancelPick() })
  document.addEventListener('click', () => ctx.value.show = false)
})
</script>

<style scoped>
.inventory-grid { padding: 8px; min-height: 200px; user-select: none; }
.empty-state { color: #888; text-align: center; padding: 40px; }

.cursor-hint {
  text-align: center; padding: 6px; margin-bottom: 8px; border-radius: 4px;
  background: rgba(255,165,0,0.15); color: #ffa500; font-size: 12px;
}

.section-title { font-size: 11px; color: #666; margin: 8px 0 4px; text-align: center; }

.main-rows { display: flex; flex-direction: column; gap: 2px; }
.inv-row { display: flex; gap: 2px; justify-content: center; }
.hotbar-row { display: flex; gap: 2px; justify-content: center; margin-top: 2px; }

.grid-slot {
  width: 44px; height: 44px; border: 2px solid #3a3a3a; border-radius: 4px;
  background: #141414; cursor: pointer; position: relative;
  transition: border-color 0.1s, transform 0.1s;
}
.grid-slot:hover { border-color: #777; }
.grid-slot.selected { border-color: #ffd700; box-shadow: 0 0 6px rgba(255,215,0,0.25); }
.grid-slot.empty-slot { opacity: 0.5; }
.grid-slot.cursor-pick { border-color: #ff8c00; border-style: dashed; transform: scale(1.04); }

.item-inner {
  position: absolute; inset: 2px; border-radius: 2px;
  display: flex; align-items: center; justify-content: center;
}
.item-name {
  font-size: 9px; color: #fff; font-weight: bold; text-align: center;
  text-shadow: 0 1px 2px rgba(0,0,0,0.8); line-height: 1.1; padding: 2px;
}
.item-count {
  position: absolute; bottom: 0; right: 2px;
  font-size: 11px; color: #fff; font-weight: bold;
  text-shadow: 0 0 3px #000;
}
.slot-idx { position: absolute; top: 0; left: 2px; font-size: 7px; color: #555; }
.slot-num { position: absolute; top: 0; left: 2px; font-size: 8px; color: #888; }

.stats-bar {
  display: flex; align-items: center; gap: 12px; margin-top: 12px; justify-content: center;
  font-size: 12px; color: #aaa;
}

.context-menu {
  position: fixed; z-index: 9999; background: #2c2c2c; border: 1px solid #555;
  border-radius: 6px; padding: 4px 0; min-width: 140px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
.menu-header { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; margin-bottom: 2px; }
.menu-item { padding: 8px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.menu-item:hover { background: #444; }
.menu-item.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }
</style>
