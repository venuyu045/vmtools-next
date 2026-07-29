<template>
  <div class="inv-container">
    <div class="help-text">
      🖱 左键=拿起/放下/交换 (和 MC 操作一样)
      <span class="sep">·</span>
      右键=丢弃菜单
      <span class="sep">·</span>
      操作后点 🔄 刷新
    </div>

    <!-- Slots 0-35 (backpack) -->
    <div class="inv-grid">
      <div v-for="row in 4" :key="row" class="inv-row">
        <div v-for="col in 9" :key="(row-1)*9+col-1"
          class="slot"
          :class="{ filled: !!getSlot((row-1)*9+col-1) }"
          :title="slotTip((row-1)*9+col-1)"
          @click.left="click((row-1)*9+col-1)"
          @click.right.prevent="rclick((row-1)*9+col-1, $event)"
        >
          <img v-if="getSlot((row-1)*9+col-1)" :src="iconUrl(getSlot((row-1)*9+col-1)!.item_id)" class="icon" :data-item-id="getSlot((row-1)*9+col-1)!.item_id" @error="onImgErr" />
          <span v-if="getSlot((row-1)*9+col-1)" class="count">{{ getSlot((row-1)*9+col-1)!.count }}</span>
        </div>
      </div>
    </div>

    <!-- Hotbar (36-44) -->
    <div class="hotbar">
      <div v-for="i in 9" :key="'h'+i"
        class="slot"
        :class="{ filled: !!getSlot(35+i), sel: (i-1) === (inventory?.selected_hotbar ?? 0) }"
        :title="slotTip(35+i)"
        @click.left="click(35+i)"
        @click.right.prevent="rclick(35+i, $event)"
      >
        <img v-if="getSlot(35+i)" :src="iconUrl(getSlot(35+i)!.item_id)" class="icon" :data-item-id="getSlot(35+i)!.item_id" @error="onImgErr" />
        <span v-if="getSlot(35+i)" class="count">{{ getSlot(35+i)!.count }}</span>
        <span class="num">{{ i }}</span>
      </div>
    </div>

    <div class="bar">
      <el-button size="small" @click="$emit('refresh')" :loading="loading">🔄 刷新</el-button>
      <span class="info">物品 {{ inventory?.total_items ?? 0 }} · 空位 {{ inventory?.empty_slots ?? 0 }}</span>
      <span v-if="history.length" class="undo" @click="undo">↩ 撤销 ({{ history.length }})</span>
    </div>

    <!-- Context menu -->
    <div v-if="menu.show" class="ctxmenu" :style="{top:menu.y+'px',left:menu.x+'px'}">
      <div class="ctxhead">{{ label(menu.item?.item_id||'') }} ×{{ menu.item?.count }}</div>
      <div class="ctxitem" @click="menuDrop('DropItemStack')">🗑 丢弃整组 (64个)</div>
      <div class="ctxitem" @click="menuDrop('DropSingleItem')">🗑 丢弃 1 个</div>
      <div class="ctxitem cancel" @click="menu.show=false">取消</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface InvSlot { slot: number; item_id: string; display_name: string; count: number }
interface InvData {
  bot_id: string; inventory_id: number; slots: InvSlot[]
  hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number
}

const props = defineProps<{ botId: string; inventory: InvData | null; loading: boolean }>()
const emit = defineEmits<{ refresh: []; action: [p: { action: string; slot_id: number }]; drop: [p: { item_type: string; count: number }] }>()

const history = ref<{ action: string; slot_id: number }[]>([])
const menu = ref({ show: false, x: 0, y: 0, item: null as InvSlot | null, slot_id: 0 })
const failedIcons = ref(new Set<string>())
const iconBase = 'https://raw.githubusercontent.com/misode/mcmeta/assets-summary/assets/minecraft/textures/item'

const sm = computed(() => {
  const m: Record<number, InvSlot> = {}
  for (const s of props.inventory?.slots || []) m[s.slot] = s
  return m
})
function getSlot(i: number) { return sm.value[i] }

function snake(id: string): string {
  return (id||'').replace('minecraft:','').replace(/([A-Z])/g,'_$1').toLowerCase().replace(/^_/,'')
}
function iconUrl(id: string): string {
  return failedIcons.value.has(id) ? '' : `${iconBase}/${snake(id)}.png`
}
function onImgErr(e: Event) {
  const img = e.target as HTMLImageElement
  failedIcons.value.add(img.dataset.itemId || '')
  img.style.display = 'none'
}
function label(id: string): string {
  return (id||'').replace('minecraft:','').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())
}
function slotTip(i: number): string {
  const s = getSlot(i)
  return s ? `${label(s.item_id)} ×${s.count}` : `空 (槽位 ${i})`
}

function click(slotIdx: number) {
  menu.value.show = false
  emit('action', { action: 'LeftClick', slot_id: slotIdx })
  history.value.push({ action: 'LeftClick', slot_id: slotIdx })
}

function rclick(slotIdx: number, e: MouseEvent) {
  const s = getSlot(slotIdx)
  if (!s) return
  menu.value = { show: true, x: Math.min(e.clientX, innerWidth-140), y: Math.min(e.clientY, innerHeight-160), item: s, slot_id: slotIdx }
}

function menuDrop(action: string) {
  if (!menu.value.item) return
  menu.value.show = false
  emit('drop', { item_type: menu.value.item.item_id, count: action === 'DropItemStack' ? 64 : 1 })
}

function undo() {
  history.value.pop()
  // Replay remaining actions: undo = send reverse action (click same slot again to put item back)
  const last = history.value[history.value.length - 1]
  if (last) emit('action', last)
  if (history.value.length === 0) emit('refresh')
}
</script>

<style scoped>
.inv-container { padding: 8px 12px; user-select: none; }
.help-text {
  text-align: center; font-size: 12px; color: #888; padding: 6px 0 10px;
}
.help-text .sep { margin: 0 8px; color: #555; }

.inv-grid { display: flex; flex-direction: column; gap: 2px; }
.inv-row { display: flex; gap: 2px; justify-content: center; }
.hotbar { display: flex; gap: 2px; justify-content: center; margin-top: 6px; }

.slot {
  width: 42px; height: 42px; border: 2px solid #3a3a3a; border-radius: 3px;
  background: #141414; cursor: pointer; position: relative;
  transition: border-color 0.1s;
}
.slot:hover { border-color: #aaa; }
.slot.filled { background: #1a1a1a; }
.slot.sel { border-color: #ffe082; box-shadow: 0 0 4px rgba(255,224,130,0.3); }
.slot .icon { position: absolute; width: 32px; height: 32px; top: 4px; left: 4px; image-rendering: pixelated; }
.slot .count {
  position: absolute; bottom: 1px; right: 3px;
  font-size: 11px; color: #fff; font-weight: bold; text-shadow: 0 0 3px #000, 0 0 3px #000;
}
.slot .num { position: absolute; top: 0; left: 2px; font-size: 8px; color: #666; }

.bar {
  display: flex; align-items: center; gap: 16px; margin-top: 12px; justify-content: center;
}
.info { font-size: 12px; color: #aaa; }
.undo { font-size: 12px; color: #ffa500; cursor: pointer; }
.undo:hover { text-decoration: underline; }

.ctxmenu {
  position: fixed; z-index: 9999; background: #2a2a2a; border: 1px solid #555;
  border-radius: 5px; padding: 4px 0; min-width: 140px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
.ctxhead { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; }
.ctxitem { padding: 7px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.ctxitem:hover { background: #444; }
.ctxitem.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }
</style>
