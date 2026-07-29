<template>
  <div class="inv-container">
    <!-- Cursor indicator -->
    <div v-if="cursorMsg" class="cursor-bar">{{ cursorMsg }}</div>

    <div class="help">
      左键=拿/放/交换 · 右键=丢弃 · 🔄刷新看结果
    </div>

    <!-- Backpack (slots 0-35) -->
    <div class="inv-grid">
      <div v-for="row in 4" :key="row" class="inv-row">
        <div v-for="col in 9" :key="(row-1)*9+col-1"
          class="slot" :class="{ filled: !!get((row-1)*9+col-1), cursor: cursorSlot === (row-1)*9+col-1 }"
          :title="tip((row-1)*9+col-1)"
          @click.left="click((row-1)*9+col-1)"
          @click.right.prevent="rclick((row-1)*9+col-1, $event)"
        >
          <img v-if="get((row-1)*9+col-1)" :src="icon(get((row-1)*9+col-1)!.item_id)" class="icon" />
          <span v-if="get((row-1)*9+col-1)" class="count">{{ get((row-1)*9+col-1)!.count }}</span>
          <span v-if="!get((row-1)*9+col-1)" class="sid">{{ (row-1)*9+col-1 }}</span>
        </div>
      </div>
    </div>

    <!-- Hotbar (slots 36-44) -->
    <div class="hotbar">
      <div v-for="i in 9" :key="'h'+i"
        class="slot" :class="{ filled: !!get(35+i), sel: (i-1) === (inventory?.selected_hotbar ?? 0), cursor: cursorSlot === 35+i }"
        :title="tip(35+i)"
        @click.left="click(35+i)"
        @click.right.prevent="rclick(35+i, $event)"
      >
        <img v-if="get(35+i)" :src="icon(get(35+i)!.item_id)" class="icon" />
        <span v-if="get(35+i)" class="count">{{ get(35+i)!.count }}</span>
        <span class="num">{{ i }}</span>
      </div>
    </div>

    <div class="bar">
      <el-button size="small" @click="doRefresh" :loading="loading">🔄 刷新</el-button>
      <span>{{ inventory?.total_items ?? 0 }} 物品 · {{ inventory?.empty_slots ?? 0 }} 空位</span>
    </div>

    <!-- Context menu -->
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

interface Slot { slot: number; item_id: string; display_name: string; count: number }
interface Data { bot_id: string; inventory_id: number; slots: Slot[]; hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number }

const p = defineProps<{ botId: string; inventory: Data | null; loading: boolean }>()
const emit = defineEmits<{ refresh: []; action: [p: { action: string; slot_id: number }]; drop: [p: { item_type: string; count: number }] }>()

const cursorSlot = ref(-1)
const cursorText = ref('')
const menu = ref({ show: false, x: 0, y: 0, item: null as Slot | null, slot_id: 0 })

const cursorMsg = computed(() => cursorSlot.value >= 0 ? `👆 已从槽位 ${cursorSlot.value} 拿起物品，再点目标格放下/交换` : '')

const sm = computed(() => {
  const m: Record<number, Slot> = {}
  for (const s of p.inventory?.slots || []) m[s.slot] = s
  return m
})
function get(i: number): Slot | undefined { return sm.value[i] }

function icon(id: string): string {
  return `https://minecraft.wiki/images/Invicon_${inviconName(id)}.png`
}

function inviconName(id: string): string {
  // ShulkerBox → Shulker_Box, PlayerHead → Player_Head, Azalea → Azalea
  return (id||'').replace('minecraft:','').replace(/([a-z])([A-Z])/g,'$1_$2')
}

function label(id: string): string {
  return (id||'').replace('minecraft:','').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())
}

function tip(i: number): string {
  const s = get(i)
  if (cursorSlot.value >= 0) {
    if (i === cursorSlot.value) return '再次点击取消'
    return s ? `交换 ${label(s.item_id)}` : '放在这里'
  }
  return s ? `${label(s.item_id)} ×${s.count}` : `空 (槽位 ${i})`
}

async function click(slotIdx: number) {
  menu.value.show = false
  if (cursorSlot.value >= 0 && cursorSlot.value === slotIdx) {
    // Click same slot → cancel pickup
    cursorSlot.value = -1
    return
  }
  emit('action', { action: 'LeftClick', slot_id: slotIdx })
  if (cursorSlot.value === -1 && get(slotIdx)) {
    // Pickup
    cursorSlot.value = slotIdx
  } else {
    // Place/swap → reset cursor, refresh after short delay
    cursorSlot.value = -1
    setTimeout(doRefresh, 300)
  }
}

function rclick(slotIdx: number, e: MouseEvent) {
  const s = get(slotIdx)
  if (!s) return
  menu.value = { show: true, x: Math.min(e.clientX, innerWidth-140), y: Math.min(e.clientY, innerHeight-160), item: s, slot_id: slotIdx }
}

function doDrop(a: string) {
  if (!menu.value.item) return
  menu.value.show = false
  emit('drop', { item_type: menu.value.item.item_id, count: a === 'DropItemStack' ? 64 : 1 })
}

function doRefresh() { cursorSlot.value = -1; emit('refresh') }

// Esc to cancel
import { onMounted } from 'vue'
onMounted(() => {
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') cursorSlot.value = -1 })
  document.addEventListener('click', () => menu.value.show = false)
})
</script>

<style scoped>
.inv-container { padding: 8px; user-select: none; }
.cursor-bar { text-align: center; padding: 5px 8px; margin-bottom: 6px; background: rgba(255,165,0,0.12); color: #ffa500; font-size: 12px; border-radius: 4px; }
.help { text-align: center; font-size: 11px; color: #777; padding: 4px 0 8px; }

.inv-grid { display: flex; flex-direction: column; gap: 2px; }
.inv-row { display: flex; gap: 2px; justify-content: center; }
.hotbar { display: flex; gap: 2px; justify-content: center; margin-top: 6px; }

.slot {
  width: 42px; height: 42px; border: 2px solid #3a3a3a; border-radius: 3px;
  background: #141414; cursor: pointer; position: relative; transition: border-color 0.1s;
}
.slot:hover { border-color: #aaa; }
.slot.filled { background: #1a1a1a; }
.slot.sel { border-color: #ffe082; box-shadow: 0 0 4px rgba(255,224,130,0.4); }
.slot.cursor { border-color: #ff8c00; border-style: dashed; background: rgba(255,140,0,0.08); }
.slot .icon { position: absolute; width: 32px; height: 32px; top: 4px; left: 4px; image-rendering: pixelated; }
.slot .count { position: absolute; bottom: 1px; right: 3px; font-size: 11px; color: #fff; font-weight: bold; text-shadow: 0 0 3px #000; }
.slot .sid { position: absolute; top: 0; left: 2px; font-size: 8px; color: #444; }
.slot .num { position: absolute; top: 0; left: 2px; font-size: 9px; color: #888; }

.bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; justify-content: center; font-size: 12px; color: #aaa; }

.ctx { position: fixed; z-index: 9999; background: #2a2a2a; border: 1px solid #555; border-radius: 5px; padding: 4px 0; min-width: 140px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
.ctxh { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; }
.ctxi { padding: 7px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.ctxi:hover { background: #444; }
.ctxi.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }
</style>
