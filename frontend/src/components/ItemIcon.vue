<template>
  <div class="item-icon" :style="{ width: size + 'px', height: size + 'px' }">
    <img
      v-if="!failed"
      :src="src"
      :alt="name || itemId"
      class="item-img"
      loading="lazy"
      draggable="false"
      @error="onError"
    />
    <span v-else class="item-emoji" :style="{ fontSize: Math.round(size * 0.55) + 'px' }">{{ emoji }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(defineProps<{
  itemId: string
  name?: string
  size?: number
}>(), {
  name: '',
  size: 40,
})

const failed = ref(false)
const key = computed(() => (props.itemId || '').split(':').pop() || '')
const src = computed(() => `/static/item-icons/${key.value}.png`)
const emoji = computed(() => itemEmoji(props.itemId))

function onError() { failed.value = true }

/** 物品类别 → emoji 兜底图标（原版贴图缺失时显示） */
function itemEmoji(itemId: string): string {
  const s = itemId.toLowerCase()
  if (s.includes('diamond')) return '💎'
  if (s.includes('emerald')) return '🟢'
  if (s.includes('netherite')) return '⚫'
  if (s.includes('gold')) return '🟡'
  if (s.includes('iron')) return '🔩'
  if (s.includes('coal')) return '⬛'
  if (s.includes('redstone')) return '🔴'
  if (s.includes('lapis')) return '🔵'
  if (s.includes('quartz')) return '🤍'
  if (s.includes('obsidian')) return '🟣'
  if (s.includes('shulker')) return '📦'
  if (s.includes('chest') || s.includes('barrel')) return '🧰'
  if (s.includes('log') || s.includes('plank') || s.includes('wood') || s.includes('bamboo')) return '🪵'
  if (s.includes('stone') || s.includes('cobblestone') || s.includes('deepslate') || s.includes('granite') || s.includes('andesite') || s.includes('diorite') || s.includes('tuff') || s.includes('sand') || s.includes('gravel') || s.includes('clay')) return '🪨'
  if (s.includes('brick') || s.includes('terracotta') || s.includes('concrete')) return '🧱'
  if (s.includes('glass') || s.includes('pane')) return '🪟'
  if (s.includes('soul') || s.includes('nether')) return '🔥'
  if (s.includes('cooked') || s.includes('beef') || s.includes('pork') || s.includes('chicken') || s.includes('fish') || s.includes('mutton')) return '🍖'
  if (s.includes('bread') || s.includes('apple') || s.includes('carrot') || s.includes('potato') || s.includes('melon') || s.includes('wheat') || s.includes('berry') || s.includes('egg') || s.includes('milk') || s.includes('pumpkin') || s.includes('beetroot')) return '🍎'
  if (s.includes('potion')) return '🧪'
  if (s.includes('sword')) return '⚔️'
  if (s.includes('pickaxe') || s.includes('axe') || s.includes('shovel') || s.includes('hoe')) return '⛏️'
  if (s.includes('helmet') || s.includes('chestplate') || s.includes('legging') || s.includes('boots')) return '🛡️'
  if (s.includes('book') || s.includes('map') || s.includes('paper')) return '📖'
  if (s.includes('ender') || s.includes('dragon') || s.includes('chorus') || s.includes('pearl') || s.includes('eye')) return '👁️'
  if (s.includes('red')) return '🔴'
  if (s.includes('blue')) return '🔵'
  if (s.includes('green')) return '🟢'
  if (s.includes('yellow')) return '🟡'
  if (s.includes('white')) return '⚪'
  if (s.includes('black')) return '⚫'
  if (s.includes('flower') || s.includes('tulip') || s.includes('rose') || s.includes('dandelion') || s.includes('poppy') || s.includes('lily') || s.includes('allium') || s.includes('orchid') || s.includes('peony') || s.includes('sunflower') || s.includes('lilac')) return '🌸'
  return '📦'
}
</script>

<style scoped>
.item-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid var(--border-subtle);
  overflow: hidden;
}
.item-img {
  width: 100%;
  height: 100%;
  image-rendering: pixelated;
  object-fit: contain;
}
.item-emoji { line-height: 1; }
</style>