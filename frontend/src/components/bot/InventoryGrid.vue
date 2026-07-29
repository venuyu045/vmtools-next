<template>
  <div class="inventory-grid">
    <div v-if="!inventory" class="empty-state">点击 🔄 刷新 加载背包数据</div>
    <div v-else>
      <!-- Help text -->
      <div class="help-bar">
        <span>🖱 左键=快速移动</span>
        <span>·</span>
        <span>🖱 右键=菜单（丢弃/移动）</span>
      </div>

      <!-- Main inventory (3 rows of 9) -->
      <div class="main-rows">
        <div v-for="row in 3" :key="row" class="inv-row">
          <div
            v-for="col in 9" :key="(row-1)*9+col-1" class="grid-slot"
            :class="{ 'has-item': getSlot((row-1)*9+col-1), 'empty-slot': !getSlot((row-1)*9+col-1) }"
            :title="slotTooltip(getSlot((row-1)*9+col-1))"
            @click.left="onSlotClick(getSlot((row-1)*9+col-1), (row-1)*9+col-1)"
            @click.right.prevent="onSlotRight(getSlot((row-1)*9+col-1), (row-1)*9+col-1)"
          >
            <template v-if="getSlot((row-1)*9+col-1)">
              <div class="item-bg" :style="{ background: itemColor(getSlot((row-1)*9+col-1)!.item_id) }" />
              <img v-if="itemIcon(getSlot((row-1)*9+col-1)!.item_id)" :src="itemIcon(getSlot((row-1)*9+col-1)!.item_id)!" class="item-icon" />
              <span v-else class="item-abbr">{{ shortName(getSlot((row-1)*9+col-1)!.item_id).slice(0, 4) }}</span>
              <span class="count-badge">{{ formatCount(getSlot((row-1)*9+col-1)!.count) }}</span>
            </template>
          </div>
        </div>
      </div>

      <!-- Hotbar row -->
      <div class="hotbar-row">
        <div
          v-for="(s, i) in hotbarSlots" :key="'h'+i" class="grid-slot"
          :class="{ selected: i === (inventory?.selected_hotbar ?? 0), 'has-item': s, 'empty-slot': !s }"
          :title="slotTooltip(s)"
          @click.left="onSlotClick(s, 36 + i)"
          @click.right.prevent="onSlotRight(s, 36 + i)"
        >
          <template v-if="s">
            <div class="item-bg" :style="{ background: itemColor(s.item_id) }" />
            <img v-if="itemIcon(s.item_id)" :src="itemIcon(s.item_id)!" class="item-icon" />
            <span v-else class="item-abbr">{{ shortName(s.item_id).slice(0, 4) }}</span>
            <span class="count-badge">{{ formatCount(s.count) }}</span>
          </template>
          <span class="slot-label">{{ 1 + i }}</span>
        </div>
      </div>

      <!-- Stats bar -->
      <div class="stats-bar">
        <el-button size="small" @click="$emit('refresh')" :loading="loading">🔄 刷新背包</el-button>
        <span class="stat">物品: {{ inventory?.total_items ?? 0 }}</span>
        <span class="stat">空位: {{ inventory?.empty_slots ?? 0 }}</span>
      </div>
    </div>

    <!-- Right-click context menu -->
    <div v-if="contextMenu.show" class="context-menu" :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }">
      <div v-if="contextMenu.item" class="menu-header">{{ formatName(contextMenu.item.item_id) }} ×{{ contextMenu.item.count }}</div>
      <div class="menu-item" @click="doContextAction('DropItemStack')">🗑 丢弃整组</div>
      <div class="menu-item" @click="doContextAction('DropSingleItem')">🗑 丢弃一个</div>
      <div class="menu-item" @click="doContextAction('ShiftClick')">📦 快速移动</div>
      <div class="menu-item" @click="doContextAction('LeftClick')">👆 左键拿取</div>
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
  action: [payload: { action: string; slot_id: number; inventory_id: number }]
  drop: [payload: { item_type: string; count: number }]
}>()

const contextMenu = ref({ show: false, x: 0, y: 0, item: null as InvSlot | null, slot_id: 0 })

const slotMap = computed(() => {
  const m: Record<number, InvSlot> = {}
  for (const s of props.inventory?.slots || []) m[s.slot] = s
  return m
})

function getSlot(idx: number): InvSlot | undefined { return slotMap.value[idx] }

const hotbarSlots = computed(() => {
  return Array.from({ length: 9 }, (_, i) => slotMap.value[36 + i] || null)
})

function formatName(id: string): string {
  return (id || '').replace('minecraft:', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function shortName(id: string): string {
  return (id || '').split(':').pop()?.replace(/_/g, ' ').slice(0, 12) || ''
}

function formatCount(n: number): string { return n >= 64 ? '64+' : String(n) }

function slotTooltip(s: InvSlot | undefined | null): string {
  if (!s) return '空'
  return `${formatName(s.item_id)} ×${s.count} (槽位 ${s.slot})`
}

function itemColor(itemId: string): string {
  const colors: Record<string, string> = {
    shulkerbox: '#9b59b6', playerhead: '#e67e22', hopper: '#7f8c8d',
    stick: '#8B4513', azalea: '#27ae60', flowingazalea: '#e91e63',
    wool: '#ecf0f1', concrete: '#95a5a6', stone: '#7f8c8d',
    dirt: '#6d4c41', wood: '#d4a574', iron: '#bdc3c7', gold: '#f1c40f',
  }
  const lower = itemId.toLowerCase()
  for (const [k, v] of Object.entries(colors)) {
    if (lower.includes(k) || lower.includes(k.replace(' ', '_'))) return v
  }
  const h = itemId.split('').reduce((v, c) => v * 31 + c.charCodeAt(0), 0)
  return `hsl(${Math.abs(h) % 360}, 45%, 40%)`
}

function itemIcon(itemId: string): string | null {
  // Return null for now — MC item icons need a CDN
  // Could use: https://api.mcasset.cloud/1.21.4/items/{item_id}.png
  return null
}

// Click handlers
function onSlotClick(slot: InvSlot | null | undefined, slotIdx: number) {
  contextMenu.value.show = false
  if (!slot) return
  emit('action', { action: 'ShiftClick', slot_id: slotIdx, inventory_id: 0 })
}

function onSlotRight(slot: InvSlot | null | undefined, slotIdx: number, e?: MouseEvent) {
  if (!slot) return
  contextMenu.value = {
    show: true,
    x: Math.min((e as MouseEvent).clientX, window.innerWidth - 150),
    y: Math.min((e as MouseEvent).clientY, window.innerHeight - 180),
    item: slot, slot_id: slotIdx,
  }
}

function doContextAction(action: string) {
  const ctx = contextMenu.value
  if (!ctx.item) return
  if (action.startsWith('Drop')) {
    emit('drop', { item_type: ctx.item.item_id, count: action === 'DropItemStack' ? 64 : 1 })
  } else {
    emit('action', { action, slot_id: ctx.slot_id, inventory_id: 0 })
  }
  ctx.show = false
}

function closeMenu() { contextMenu.value.show = false }
onMounted(() => document.addEventListener('click', closeMenu))
onUnmounted(() => document.removeEventListener('click', closeMenu))
</script>

<style scoped>
.inventory-grid { padding: 12px; min-height: 200px; user-select: none; }
.empty-state { color: #888; text-align: center; padding: 40px; }

.help-bar {
  display: flex; gap: 8px; justify-content: center; padding: 8px 0 12px;
  font-size: 12px; color: #888;
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
.grid-slot.selected { border-color: #ffd700; border-width: 2.5px; box-shadow: 0 0 8px rgba(255,215,0,0.3); }
.grid-slot.empty-slot { opacity: 0.6; }

.item-bg {
  position: absolute; inset: 2px; border-radius: 2px; opacity: 0.3;
}
.item-icon { position: absolute; width: 32px; height: 32px; top: 6px; left: 6px; image-rendering: pixelated; }
.item-abbr {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  font-size: 10px; color: #eee; font-weight: bold; text-shadow: 0 1px 2px #000;
  white-space: nowrap; overflow: hidden; max-width: 40px;
}
.count-badge {
  position: absolute; bottom: 1px; right: 3px;
  font-size: 11px; color: #fff; font-weight: bold;
  text-shadow: 0 0 2px #000, 0 0 2px #000;
}
.slot-label {
  position: absolute; top: 0; left: 2px;
  font-size: 8px; color: #666;
}

.stats-bar {
  display: flex; align-items: center; gap: 16px; margin-top: 12px; justify-content: center;
}
.stat { font-size: 12px; color: #aaa; }

.context-menu {
  position: fixed; z-index: 9999; background: #2c2c2c; border: 1px solid #555;
  border-radius: 6px; padding: 4px 0; min-width: 150px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
.menu-header { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; margin-bottom: 2px; }
.menu-item { padding: 8px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.menu-item:hover { background: #444; }
.menu-item.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }
</style>
