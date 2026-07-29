<template>
  <div ref="container" class="build2d-container">
    <canvas ref="canvas" class="map-canvas" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'

const props = defineProps<{
  taskId: string
  materials?: { item_id: string; display_name: string; placed: number; required: number }[]
  initData?: { blocks: { x: number; y: number; z: number; expected: string; placed: boolean }[]; origin: { x: number; y: number; z: number }; size: { x: number; z: number } } | null
}>()

const emit = defineEmits<{ ready: [] }>()

const container = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()

const COLORS: Record<string, string> = {
  'minecraft:white_wool': '#FFFFFF', 'minecraft:orange_wool': '#F9801D',
  'minecraft:magenta_wool': '#C74EBD', 'minecraft:light_blue_wool': '#3AB3DA',
  'minecraft:yellow_wool': '#FED83D', 'minecraft:lime_wool': '#80C71F',
  'minecraft:pink_wool': '#F38BAA', 'minecraft:gray_wool': '#474F52',
  'minecraft:light_gray_wool': '#9D9D97', 'minecraft:cyan_wool': '#169C9D',
  'minecraft:purple_wool': '#8932B8', 'minecraft:blue_wool': '#3C44AA',
  'minecraft:brown_wool': '#835432', 'minecraft:green_wool': '#5E7C16',
  'minecraft:red_wool': '#B02E26', 'minecraft:black_wool': '#1D1D21',
  'minecraft:white_concrete': '#CFD5D6', 'minecraft:orange_concrete': '#E06300',
}

function blockColor(blockId: string): string {
  // Strip properties: "minecraft:white_wool[facing=north]" -> "minecraft:white_wool"
  const clean = blockId.split('[')[0]
  return COLORS[clean] ?? `#${((clean.split('').reduce((h, c) => h * 31 + c.charCodeAt(0), 0) & 0xFFFFFF) >>> 0).toString(16).padStart(6, '0')}`
}

function render() {
  const cvs = canvas.value
  if (!cvs || !props.initData?.blocks?.length) return

  const blocks = props.initData.blocks
  const size = props.initData.size
  const ctx = cvs.getContext('2d')!

  // Calculate bounds
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
  for (const b of blocks) { minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x); minZ = Math.min(minZ, b.z); maxZ = Math.max(maxZ, b.z) }

  const cols = maxX - minX + 1
  const rows = maxZ - minZ + 1

  // Cell size to fill canvas
  const cw = cvs.clientWidth
  const ch = cvs.clientHeight - 60  // leave room for coordinates
  const cellSize = Math.max(4, Math.min(40, Math.floor(Math.min(cw / cols, ch / rows))))
  const totalW = cols * cellSize
  const totalH = rows * cellSize
  const offsetX = Math.floor((cw - totalW) / 2)
  const offsetY = Math.floor((ch - totalH) / 2) + 30

  // HiDPI
  const dpr = window.devicePixelRatio || 1
  cvs.width = cw * dpr
  cvs.height = (ch + 40) * dpr
  cvs.style.width = cw + 'px'
  cvs.style.height = (ch + 40) + 'px'
  ctx.scale(dpr, dpr)

  // Draw grid
  ctx.fillStyle = '#1a1a2e'
  ctx.fillRect(0, 0, cw, ch + 40)

  let placed = 0
  for (const b of blocks) {
    const cx = offsetX + (b.x - minX) * cellSize
    const cy = offsetY + (b.z - minZ) * cellSize
    const color = b.placed ? blockColor(b.expected) : '#444444'
    ctx.fillStyle = color
    ctx.fillRect(cx, cy, cellSize, cellSize)
    if (!b.placed) {
      ctx.strokeStyle = '#666666'
      ctx.lineWidth = 0.5
      ctx.strokeRect(cx, cy, cellSize, cellSize)
    }
    if (b.placed) placed++
  }

  // Axis labels
  ctx.fillStyle = '#888888'
  ctx.font = '11px monospace'
  ctx.fillText(`Z: ${minZ} → ${maxZ}  (${rows} rows)`, 10, 16)
  ctx.fillText(`X: ${minX} → ${maxX}  (${cols} cols)   Placed: ${placed}/${blocks.length}`, 10, 32)
  ctx.fillText(`Y level: ${blocks[0]?.y ?? '?'}`, 10, 48)

  emit('ready')
}

watch(() => props.initData, () => nextTick(render), { deep: true })

onMounted(() => nextTick(render))

onUnmounted(() => {})

defineExpose({ refresh: render })
</script>

<style scoped>
.build2d-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
  background: #1a1a2e;
  border-radius: 8px;
  overflow: hidden;
}
.map-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
