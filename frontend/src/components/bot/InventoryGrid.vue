<template>
  <div class="inventory-grid">
    <div v-if="!inventory" class="empty-state">点击「刷新背包」加载数据</div>
    <div v-else class="inventory-content">
      <!-- Player model area (left) -->
      <div class="player-area">
        <div class="armor-slots">
          <div class="armor-slot" v-for="(s, i) in armorSlots" :key="'a'+i" :title="s?.item_id || 'empty'">
            <div v-if="s" class="filled" :style="{ background: slotColor(s) }">
              <span class="count">{{ s.count }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Main grid (right) -->
      <div class="main-area">
        <!-- Hotbar row (bottom) -->
        <div class="hotbar-row">
          <div
            v-for="(s, i) in reversedHotbar"
            :key="'h'+i"
            class="grid-slot"
            :class="{ selected: (8 - i) === (inventory?.selected_hotbar ?? 0) }"
            @click.left="onSlotClick(s, 27 + i)"
            @click.right.prevent="onSlotRight(s, 27 + i)"
          >
            <div v-if="s" class="item" :style="{ background: slotColor(s) }">
              <span class="item-name">{{ shortName(s.item_id) }}</span>
              <span class="item-count">{{ s.count }}</span>
            </div>
            <span class="slot-num">{{ 1 + i }}</span>
          </div>
        </div>

        <!-- Main inventory (3 rows of 9) -->
        <div class="main-rows">
          <div v-for="row in 3" :key="row" class="inv-row">
            <div
              v-for="col in 9"
              :key="(row-1)*9+col-1"
              class="grid-slot"
              @click.left="onSlotClick(getSlot((row-1)*9+col-1), (row-1)*9+col-1)"
              @click.right.prevent="onSlotRight(getSlot((row-1)*9+col-1), (row-1)*9+col-1)"
            >
              <div v-if="getSlot((row-1)*9+col-1)" class="item" :style="{ background: slotColor(getSlot((row-1)*9+col-1)!) }">
                <span class="item-name">{{ shortName(getSlot((row-1)*9+col-1)!.item_id) }}</span>
                <span class="item-count">{{ getSlot((row-1)*9+col-1)!.count }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="action-bar">
        <el-button size="small" @click="$emit('refresh')" :loading="loading">🔄 刷新</el-button>
        <span class="info">空位: {{ inventory?.empty_slots }} | 物品: {{ inventory?.total_items }}</span>
      </div>
    </div>

    <!-- Right-click context menu -->
    <div v-if="contextMenu.show" class="context-menu" :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }">
      <div v-if="contextMenu.item" class="menu-header">{{ shortName(contextMenu.item.item_id) }} ×{{ contextMenu.item.count }}</div>
      <div class="menu-item" @click="doContextAction('DropItemStack')">🗑 丢弃整组</div>
      <div class="menu-item" @click="doContextAction('DropSingleItem')">🗑 丢弃一个</div>
      <div class="menu-item" @click="doContextAction('ShiftClick')">📦 快速移动</div>
      <div class="menu-item" @click="contextMenu.show = false">取消</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface InventorySlot {
  slot: number; item_id: string; display_name: string; count: number
}

interface InventoryData {
  bot_id: string; inventory_id: number; slots: InventorySlot[]
  hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number
}

const props = defineProps<{
  botId: string
  inventory: InventoryData | null
  loading: boolean
}>()

const emit = defineEmits<{
  refresh: []
  action: [payload: { action: string; slot_id: number; inventory_id: number }]
  drop: [payload: { item_type: string; count: number }]
}>()

const contextMenu = ref({ show: false, x: 0, y: 0, item: null as InventorySlot | null, slot_id: 0 })

// Slot index → slot data map
const slotMap = computed(() => {
  const m: Record<number, InventorySlot> = {}
  for (const s of props.inventory?.slots || []) m[s.slot] = s
  return m
})

function getSlot(idx: number): InventorySlot | undefined {
  return slotMap.value[idx]
}

const reversedHotbar = computed(() => {
  const h = props.inventory?.hotbar || []
  return [...h].reverse().map((si: number) => slotMap.value[si] || null)
})

const armorSlots = computed(() => {
  return [36, 37, 38, 39].map(i => slotMap.value[i] || null)
})

function shortName(id: string): string {
  return (id || '').split(':').pop()?.replace('_', ' ') || ''
}

function slotColor(s: InventorySlot): string {
  const h = (s.item_id || '').split('').reduce((v: number, c: string) => v * 31 + c.charCodeAt(0), 0)
  return `hsl(${Math.abs(h) % 360}, 40%, 35%)`
}

function onSlotClick(slot: InventorySlot | null | undefined, slotIdx: number) {
  contextMenu.value.show = false
  if (!slot) return
  // Left click = shift click (quick move)
  emit('action', { action: 'ShiftClick', slot_id: slotIdx, inventory_id: 0 })
}

function onSlotRight(slot: InventorySlot | null | undefined, slotIdx: number, e?: MouseEvent) {
  if (!slot) return
  contextMenu.value = { show: true, x: (e as MouseEvent).clientX, y: (e as MouseEvent).clientY, item: slot, slot_id: slotIdx }
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

function closeMenu(e: MouseEvent) {
  contextMenu.value.show = false
}

onMounted(() => document.addEventListener('click', closeMenu))
onUnmounted(() => document.removeEventListener('click', closeMenu))
</script>

<style scoped>
.inventory-grid { padding: 12px; min-height: 200px; }
.empty-state { color: #888; text-align: center; padding: 40px; }
.inventory-content { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }

.player-area { width: 60px; }
.armor-slots { display: flex; flex-direction: column; gap: 4px; padding-top: 20px; }
.armor-slot { width: 44px; height: 44px; border: 1px solid #555; border-radius: 4px; background: #2a2a2a; }
.armor-slot .filled { width: 100%; height: 100%; border-radius: 3px; display: flex; align-items: flex-end; justify-content: flex-end; }
.armor-slot .count { font-size: 10px; color: #fff; text-shadow: 0 0 2px #000; padding: 2px; }

.main-area { flex: 1; min-width: 300px; }

.hotbar-row { display: flex; gap: 2px; margin-bottom: 6px; }
.hotbar-row .grid-slot { border-color: #444; }
.main-rows { display: flex; flex-direction: column; gap: 2px; }
.inv-row { display: flex; gap: 2px; }

.grid-slot {
  width: 36px; height: 36px; border: 1.5px solid #555; border-radius: 3px;
  background: #1a1a1a; cursor: pointer; position: relative; transition: border-color 0.15s;
}
.grid-slot:hover { border-color: #aaa; }
.grid-slot.selected { border-color: #fff; border-width: 2px; }
.grid-slot .item { width: 100%; height: 100%; border-radius: 2px; }
.grid-slot .item-count { position: absolute; bottom: 0; right: 2px; font-size: 10px; color: #fff; text-shadow: 0 0 2px #000; font-weight: bold; }
.grid-slot .item-name { position: absolute; top: 0; left: 2px; font-size: 7px; color: #ddd; white-space: nowrap; overflow: hidden; max-width: 30px; }
.grid-slot .slot-num { position: absolute; bottom: 0; left: 1px; font-size: 8px; color: #555; }

.action-bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; width: 100%; }
.action-bar .info { font-size: 12px; color: #888; }

.context-menu {
  position: fixed; z-index: 9999; background: #2a2a2a; border: 1px solid #555;
  border-radius: 4px; padding: 4px 0; min-width: 140px; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.menu-header { padding: 4px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; margin-bottom: 2px; }
.menu-item { padding: 6px 12px; font-size: 13px; cursor: pointer; color: #ccc; }
.menu-item:hover { background: #444; }
</style>
