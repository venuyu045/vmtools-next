<template>
  <div class="inventory-grid">
    <div v-if="!inventory" class="empty-state">点击 🔄 刷新 加载背包数据</div>
    <div v-else>
      <!-- Cursor item (picked up) -->
      <div v-if="cursorItem" class="cursor-item">
        <img :src="iconUrl(cursorItem.item_id)" class="cursor-icon" @error="onIconError" />
        <span class="cursor-count">{{ formatCount(cursorItem.count) }}</span>
      </div>

      <!-- Help text -->
      <div class="help-bar">
        <span>🖱 左键物品=拿起</span>
        <span>·</span>
        <span>🖱 左键空格=放下</span>
        <span>·</span>
        <span>🖱 右键=丢弃菜单</span>
      </div>

      <!-- Main inventory (3 rows of 9, slots 0-26) -->
      <div class="main-rows">
        <div v-for="row in 3" :key="row" class="inv-row">
          <div
            v-for="col in 9" :key="(row-1)*9+col-1" class="grid-slot"
            :class="slotClass((row-1)*9+col-1)"
            :title="slotTooltip(getSlot((row-1)*9+col-1))"
            @click.left="onLeftClick((row-1)*9+col-1)"
            @click.right.prevent="onRightClick((row-1)*9+col-1, $event)"
          >
            <template v-if="getSlot((row-1)*9+col-1)">
              <img
                :src="iconUrl(getSlot((row-1)*9+col-1)!.item_id)"
                class="item-icon"
                @error="(e: Event) => (e.target as HTMLImageElement).style.display='none'"
              />
              <span
                v-if="!iconLoaded(getSlot((row-1)*9+col-1)!.item_id)"
                class="item-abbr"
              >{{ shortName(getSlot((row-1)*9+col-1)!.item_id).slice(0, 4) }}</span>
              <span class="count-badge">{{ formatCount(getSlot((row-1)*9+col-1)!.count) }}</span>
            </template>
          </div>
        </div>
      </div>

      <!-- Hotbar row (slots 36-44) -->
      <div class="hotbar-row">
        <div
          v-for="i in 9" :key="'h'+i" class="grid-slot"
          :class="[slotClass(35 + i), { selected: (i - 1) === (inventory?.selected_hotbar ?? 0) }]"
          :title="slotTooltip(getSlot(35 + i))"
          @click.left="onLeftClick(35 + i)"
          @click.right.prevent="onRightClick(35 + i, $event)"
        >
          <template v-if="getSlot(35 + i)">
            <img
              :src="iconUrl(getSlot(35 + i)!.item_id)"
              class="item-icon"
              @error="(e: Event) => (e.target as HTMLImageElement).style.display='none'"
            />
            <span
              v-if="!iconLoaded(getSlot(35 + i)!.item_id)"
              class="item-abbr"
            >{{ shortName(getSlot(35 + i)!.item_id).slice(0, 4) }}</span>
            <span class="count-badge">{{ formatCount(getSlot(35 + i)!.count) }}</span>
          </template>
          <span class="slot-num">{{ i }}</span>
        </div>
      </div>

      <!-- Stats bar -->
      <div class="stats-bar">
        <el-button size="small" @click="$emit('refresh')" :loading="loading">🔄 刷新背包</el-button>
        <span class="stat">物品: {{ inventory?.total_items ?? 0 }}</span>
        <span class="stat">空位: {{ inventory?.empty_slots ?? 0 }}</span>
        <span v-if="cursorItem" class="stat cursor-hint">⌨ 按 Esc 取消选中</span>
      </div>
    </div>

    <!-- Right-click context menu -->
    <div v-if="contextMenu.show" class="context-menu" :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }">
      <div v-if="contextMenu.item" class="menu-header">{{ formatName(contextMenu.item.item_id) }} ×{{ contextMenu.item.count }}</div>
      <div class="menu-item" @click="doContextDrop('DropItemStack')">🗑 丢弃整组</div>
      <div class="menu-item" @click="doContextDrop('DropSingleItem')">🗑 丢弃一个</div>
      <div class="menu-item" @click="doContextMove('ShiftClick')">📦 快速移动到箱子</div>
      <div class="menu-item cancel" @click="contextMenu.show = false">取消</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface InvSlot {
  slot: number; item_id: string; display_name: string; count: number
}

interface InvData {
  bot_id: string; inventory_id: number; slots: InvSlot[]
  hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number
}

const props = defineProps<{ botId: string; inventory: InvData | null; loading: boolean }>()
const emit = defineEmits<{
  refresh: []
  action: [payload: { action: string; slot_id: number; from_slot?: number }]
  drop: [payload: { item_type: string; count: number }]
}>()

const contextMenu = ref({ show: false, x: 0, y: 0, item: null as InvSlot | null, slot_id: 0 })
const cursorItem = ref<InvSlot | null>(null)   // picked-up item
const cursorFromSlot = ref(-1)                   // slot picked from

const slotMap = computed(() => {
  const m: Record<number, InvSlot> = {}
  for (const s of props.inventory?.slots || []) m[s.slot] = s
  return m
})

function getSlot(idx: number): InvSlot | undefined { return slotMap.value[idx] }
function slotClass(idx: number) {
  return {
    'has-item': getSlot(idx),
    'empty-slot': !getSlot(idx),
    'cursor-source': idx === cursorFromSlot.value,
  }
}

// ── Item visual ──────────────────────

function formatName(id: string): string {
  return (id || '').replace('minecraft:', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function shortName(id: string): string {
  return (id || '').split(':').pop()?.replace(/_/g, ' ').slice(0, 12) || ''
}

function formatCount(n: number): string { return n > 9999 ? (n / 1000).toFixed(1) + 'k' : String(n) }

function snakeCase(id: string): string {
  return (id || '').replace('minecraft:', '').replace(/([A-Z])/g, '_$1').toLowerCase().replace(/^_/, '')
}

function iconUrl(itemId: string): string {
  const name = snakeCase(itemId)
  return `https://raw.githubusercontent.com/misode/mcmeta/assets-summary/textures/item/${name}.png`
}

function iconLoaded(_itemId: string): boolean {
  // Track via img @error event
  return false
}

function slotTooltip(s: InvSlot | undefined | null): string {
  if (!s) return cursorItem.value ? '放置物品' : '空'
  return `${formatName(s.item_id)} ×${s.count}`
}

// ── Click handlers ────────────────────

function onLeftClick(slotIdx: number) {
  contextMenu.value.show = false

  const slotItem = getSlot(slotIdx)

  if (cursorItem.value) {
    // Have item in hand — try to place/swap
    emit('action', {
      action: 'LeftClick',
      slot_id: slotIdx,
      from_slot: cursorFromSlot.value,
    })
    cursorItem.value = null
    cursorFromSlot.value = -1
    return
  }

  if (slotItem) {
    // Pick up item
    cursorItem.value = slotItem
    cursorFromSlot.value = slotIdx
  }
}

function onRightClick(slotIdx: number, e: MouseEvent) {
  const slotItem = getSlot(slotIdx)
  if (!slotItem) return
  contextMenu.value = {
    show: true,
    x: Math.min(e.clientX, window.innerWidth - 150),
    y: Math.min(e.clientY, window.innerHeight - 180),
    item: slotItem, slot_id: slotIdx,
  }
}

function doContextMove(action: string) {
  const ctx = contextMenu.value
  if (!ctx.item) return
  ctx.show = false
  emit('action', { action, slot_id: ctx.slot_id })
}

function doContextDrop(dropType: string) {
  const ctx = contextMenu.value
  if (!ctx.item) return
  ctx.show = false
  emit('drop', { item_type: ctx.item.item_id, count: dropType === 'DropItemStack' ? 64 : 1 })
}

function cancelDrag() {
  cursorItem.value = null
  cursorFromSlot.value = -1
}

function closeMenu() { contextMenu.value.show = false }

onMounted(() => {
  document.addEventListener('click', closeMenu)
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') cancelDrag() })
})
onUnmounted(() => document.removeEventListener('click', closeMenu))
</script>

<style scoped>
.inventory-grid { padding: 12px; min-height: 200px; user-select: none; position: relative; }
.empty-state { color: #888; text-align: center; padding: 40px; }

.help-bar {
  display: flex; gap: 8px; justify-content: center; padding: 8px 0 12px;
  font-size: 12px; color: #888;
}

.cursor-item {
  position: fixed; z-index: 10000; pointer-events: none;
  top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 64px; height: 64px; opacity: 0.85;
}
.cursor-icon { width: 100%; height: 100%; image-rendering: pixelated; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5)); }
.cursor-count {
  position: absolute; bottom: -6px; right: -6px;
  background: #1a1a1a; color: #fff; font-size: 12px; font-weight: bold;
  padding: 1px 6px; border-radius: 10px; border: 1px solid #555;
}

.main-rows { display: flex; flex-direction: column; gap: 2px; margin-bottom: 8px; }
.inv-row { display: flex; gap: 2px; justify-content: center; }

.hotbar-row { display: flex; gap: 2px; justify-content: center; margin-top: 4px; }

.grid-slot {
  width: 48px; height: 48px; border: 2px solid #444; border-radius: 4px;
  background: #1a1a1a; cursor: pointer; position: relative;
  transition: border-color 0.15s, transform 0.1s;
}
.grid-slot:hover { border-color: #aaa; transform: scale(1.05); z-index: 1; }
.grid-slot.selected { border-color: #ffd700; box-shadow: 0 0 8px rgba(255,215,0,0.3); }
.grid-slot.empty-slot { opacity: 0.6; }
.grid-slot.cursor-source { border-style: dashed; border-color: #ffa500; }

.item-icon {
  position: absolute; width: 36px; height: 36px; top: 5px; left: 5px;
  image-rendering: pixelated;
}
.item-abbr {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  font-size: 10px; color: #ccc; font-weight: bold;
  text-shadow: 0 1px 2px #000; white-space: nowrap; overflow: hidden; max-width: 40px;
}
.count-badge {
  position: absolute; bottom: 1px; right: 3px;
  font-size: 11px; color: #fff; font-weight: bold;
  text-shadow: 0 0 2px #000, 0 0 2px #000;
}
.slot-num { position: absolute; top: 0; left: 2px; font-size: 8px; color: #666; }

.stats-bar {
  display: flex; align-items: center; gap: 16px; margin-top: 12px; justify-content: center;
}
.stat { font-size: 12px; color: #aaa; }
.cursor-hint { color: #ffa500; }

.context-menu {
  position: fixed; z-index: 9999; background: #2c2c2c; border: 1px solid #555;
  border-radius: 6px; padding: 4px 0; min-width: 150px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
.menu-header { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; margin-bottom: 2px; }
.menu-item { padding: 8px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.menu-item:hover { background: #444; }
.menu-item.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }
</style>
