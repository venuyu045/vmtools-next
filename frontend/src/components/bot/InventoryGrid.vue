<template>
  <div class="inv-container">
    <div v-if="cursorMsg" class="cursor-bar">{{ cursorMsg }}</div>
    <div class="help">{{ p.clickable ? '左键=拿/放/交换 · 右键=丢弃 · 🔄刷新看结果' : 'MF 模式：仅查看背包 · 右键丢弃 · 🔄刷新（mineflayer 不支持窗口点击）' }}</div>

    <div class="layout">
      <!-- Main inventory: slots 9-35 (3 rows), with armor/offhand on right -->
      <div class="main-area">
        <div class="inv-rows">
          <div v-for="row in 3" :key="row" class="inv-row">
            <div v-for="col in 9" :key="9+(row-1)*9+col-1"
              class="slot" :class="slotCls(9+(row-1)*9+col-1)"
              :title="tip(9+(row-1)*9+col-1)"
              @click.left="click(9+(row-1)*9+col-1)"
              @click.right.prevent="rclick(9+(row-1)*9+col-1, $event)"
            >
              <ItemIcon v-if="get(9+(row-1)*9+col-1)" :item-id="get(9+(row-1)*9+col-1)!.item_id" :name="label(get(9+(row-1)*9+col-1)!.item_id)" :size="32" class="icon" />
              <span v-if="get(9+(row-1)*9+col-1)" class="count">{{ get(9+(row-1)*9+col-1)!.count }}</span>
            </div>
          </div>
        </div>

        <!-- Hotbar: slots 0-8 -->
        <div class="hotbar-row">
          <div v-for="i in 9" :key="'h'+i"
            class="slot" :class="[slotCls(i-1), { sel: (i-1) === (inventory?.selected_hotbar ?? 0) }]"
            :title="tip(i-1)"
            @click.left="click(i-1)"
            @click.right.prevent="rclick(i-1, $event)"
          >
            <ItemIcon v-if="get(i-1)" :item-id="get(i-1)!.item_id" :name="label(get(i-1)!.item_id)" :size="32" class="icon" />
            <span v-if="get(i-1)" class="count">{{ get(i-1)!.count }}</span>
            <span class="num">{{ i }}</span>
          </div>
        </div>
      </div>

      <!-- Armor 36-39 + Offhand 40 + Crafting 41-44 -->
      <div class="side-area">
        <div class="side-label">Armor</div>
        <div v-for="(armor, i) in ['头','胸','腿','脚','副']" :key="'a'+i"
          class="slot" :class="slotCls(36+i)"
          :title="armor + ': ' + tip(36+i)"
          @click.left="click(36+i)"
          @click.right.prevent="rclick(36+i, $event)"
        >
          <ItemIcon v-if="get(36+i)" :item-id="get(36+i)!.item_id" :name="label(get(36+i)!.item_id)" :size="32" class="icon" />
          <span v-if="get(36+i)" class="count">{{ get(36+i)!.count }}</span>
          <span class="num">{{ armor }}</span>
        </div>
        <div class="side-label" style="margin-top:8px">Craft</div>
        <div class="craft-grid">
          <div v-for="(s, i) in [41,42,43,44,45]" :key="'c'+s"
            class="slot" :class="[slotCls(s), { out: s === 45 }]"
            :title="(s===45?'输出':'合成') + ': ' + tip(s)"
            @click.left="click(s)"
            @click.right.prevent="rclick(s, $event)"
          >
            <ItemIcon v-if="get(s)" :item-id="get(s)!.item_id" :name="label(get(s)!.item_id)" :size="32" class="icon" />
            <span v-if="get(s)" class="count">{{ get(s)!.count }}</span>
          </div>
        </div>
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
import ItemIcon from '@/components/ItemIcon.vue'

interface Slot { slot: number; item_id: string; display_name: string; count: number }
interface Data { bot_id: string; inventory_id: number; slots: Slot[]; hotbar: number[]; selected_hotbar: number; empty_slots: number; total_items: number }

const p = defineProps<{ botId: string; inventory: Data | null; loading: boolean; clickable?: boolean }>()
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

function label(id: string): string {
  return (id||'').replace('minecraft:','').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())
}

function tip(i: number): string {
  const s = get(i)
  if (s) return `${label(s.item_id)} ×${s.count}`
  return `空`
}

function slotCls(i: number) {
  return {
    filled: !!get(i),
    cursor: cursorSlot.value === i,
  }
}

async function click(slotIdx: number) {
  menu.value.show = false
  // MF（mineflayer）不支持窗口槽位点击：仅允许查看/右键丢弃
  if (p.clickable === false) return
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
.slot .icon { position: absolute; width: 32px; height: 32px; top: 4px; left: 4px; image-rendering: pixelated; }
.slot .count { position: absolute; bottom: 1px; right: 3px; font-size: 11px; color: #fff; font-weight: bold; text-shadow: 0 0 3px #000; }
.slot .num { position: absolute; top: 0; left: 2px; font-size: 9px; color: #888; }

.bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; justify-content: center; font-size: 12px; color: #aaa; }

.ctx { position: fixed; z-index: 9999; background: #2a2a2a; border: 1px solid #555; border-radius: 5px; padding: 4px 0; min-width: 140px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
.ctxh { padding: 6px 12px; font-size: 12px; color: #aaa; border-bottom: 1px solid #444; }
.ctxi { padding: 7px 14px; font-size: 13px; cursor: pointer; color: #ddd; }
.ctxi:hover { background: #444; }
.ctxi.cancel { color: #999; border-top: 1px solid #444; margin-top: 2px; }
</style>
