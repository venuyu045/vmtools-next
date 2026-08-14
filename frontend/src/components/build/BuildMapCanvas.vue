<template>
  <div ref="container" class="build2d-container">
    <canvas ref="canvas" class="map-canvas" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { mapArtApi } from '@/api/mapArt'

/**
 * 地图画 2D 俯视预览画布（2026-08-14 完善）：
 * - 视角：正上方中心往下（俯视），按投影尺寸自适应居中
 * - 方块渲染：使用 item-icons 官方贴图；已放置=正常显示，未放置=半透明虚化
 * - bot 标记：build_bot_status 推送的实时位置 → 画布上按 bot 颜色画圆点 + 名字
 * - 贴图加载失败回退纯色块（不阻塞渲染）
 */

export interface BotMarker {
  bot_id: string
  bot_name?: string
  state?: string
  position?: { x: number; y: number; z: number } | null
  color?: string
}

const props = defineProps<{
  taskId: string
  materials?: { item_id: string; display_name: string; placed: number; required: number }[]
  initData?: { blocks: { x: number; y: number; z: number; expected: string; placed: boolean }[]; origin: { x: number; y: number; z: number }; size: { x: number; z: number } } | null
  /** 2026-08-14：bot 实时位置标记（build_bot_status 推送） */
  botPositions?: BotMarker[]
}>()

const emit = defineEmits<{ ready: [] }>()

const container = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()

// ── 贴图缓存：/static/item-icons/{pure_id}.png ──
const textureCache = new Map<string, HTMLImageElement>()
const textureLoading = new Map<string, Promise<void>>()

function loadTexture(itemId: string): Promise<void> {
  if (textureCache.has(itemId)) return Promise.resolve()
  if (textureLoading.has(itemId)) return textureLoading.get(itemId)!
  const pure = (itemId || '').split(':').pop() || ''
  if (!pure) return Promise.resolve()
  const p = new Promise<void>((resolve) => {
    const img = new Image()
    img.onload = () => { textureCache.set(itemId, img); resolve() }
    img.onerror = () => resolve() // 加载失败 → 回退纯色
    img.src = `/static/item-icons/${pure}.png`
  })
  textureLoading.set(itemId, p)
  return p
}

/** 预加载本任务用到的全部材料贴图（材料数通常 ≤ 几十，一次加载） */
async function preloadTextures() {
  const ids = new Set<string>()
  for (const m of props.materials || []) ids.add(m.item_id)
  for (const b of props.initData?.blocks || []) ids.add(b.expected)
  await Promise.all([...ids].map(id => loadTexture(id)))
}

// ── 颜色：稳定哈希（同一 bot 永远同色，重启不漂移） ──
function stableColor(seed: string): string {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  const c = (h >>> 0) & 0xFFFFFF
  return `#${c.toString(16).padStart(6, '0')}`
}

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
  const clean = blockId.split('[')[0]
  return COLORS[clean] ?? stableColor(clean)
}

/** 当前渲染用的几何参数（bounds / 格子尺寸 / 偏移），供 bot 标记复算坐标 */
interface Geo {
  minX: number; maxX: number; minZ: number; maxZ: number
  cellSize: number; offsetX: number; offsetY: number
}

function computeGeo(cw: number, ch: number): Geo | null {
  const blocks = props.initData?.blocks
  if (!blocks?.length) return null
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
  for (const b of blocks) {
    minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x)
    minZ = Math.min(minZ, b.z); maxZ = Math.max(maxZ, b.z)
  }
  const cols = maxX - minX + 1
  const rows = maxZ - minZ + 1
  const cellSize = Math.max(4, Math.min(40, Math.floor(Math.min(cw / cols, ch / rows))))
  const totalW = cols * cellSize
  const totalH = rows * cellSize
  return {
    minX, maxX, minZ, maxZ,
    cellSize,
    offsetX: Math.floor((cw - totalW) / 2),
    offsetY: Math.floor((ch - totalH) / 2) + 30,
  }
}

function drawBlock(ctx: CanvasRenderingContext2D, cx: number, cy: number, cs: number, blockId: string, placed: boolean) {
  const clean = blockId.split('[')[0]
  const img = textureCache.get(clean) ?? textureCache.get(blockId)
  if (img) {
    // 贴图渲染：已放置正常，未放置半透明虚化（用户：没建造的建议虚化一点）
    ctx.globalAlpha = placed ? 1 : 0.4
    ctx.drawImage(img, cx, cy, cs, cs)
    ctx.globalAlpha = 1
    if (!placed) {
      ctx.strokeStyle = 'rgba(255,255,255,0.25)'
      ctx.lineWidth = 0.5
      ctx.strokeRect(cx + 0.5, cy + 0.5, cs - 1, cs - 1)
    }
  } else {
    // 贴图未加载/缺失 → 纯色块兜底
    ctx.fillStyle = placed ? blockColor(blockId) : '#444444'
    ctx.fillRect(cx, cy, cs, cs)
    if (!placed) {
      ctx.strokeStyle = '#666666'
      ctx.lineWidth = 0.5
      ctx.strokeRect(cx, cy, cs, cs)
    }
  }
}

function drawBotMarkers(ctx: CanvasRenderingContext2D, geo: Geo) {
  const bots = props.botPositions || []
  if (!bots.length) return
  const r = Math.max(4, Math.round(geo.cellSize * 0.35))
  for (const b of bots) {
    if (!b.position || b.position.x == null || b.position.z == null) continue
    const cx = geo.offsetX + (b.position.x - geo.minX) * geo.cellSize
    const cy = geo.offsetY + (b.position.z - geo.minZ) * geo.cellSize
    const color = b.color || stableColor(b.bot_id)
    // 外圈白边 + 内圆（保证任何底色上都清晰）
    ctx.beginPath()
    ctx.arc(cx, cy, r + 2, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(255,255,255,0.9)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill()
    ctx.lineWidth = 1
    ctx.strokeStyle = 'rgba(0,0,0,0.6)'
    ctx.stroke()
    // bot 名标注
    ctx.font = '10px monospace'
    ctx.fillStyle = '#ffffff'
    ctx.shadowColor = 'rgba(0,0,0,0.9)'
    ctx.shadowBlur = 3
    ctx.fillText(b.bot_name || b.bot_id, cx + r + 2, cy + 4)
    ctx.shadowBlur = 0
  }
}

function render() {
  const cvs = canvas.value
  if (!cvs || !props.initData?.blocks?.length) return

  const cw = cvs.clientWidth
  const ch = cvs.clientHeight - 60
  const geo = computeGeo(cw, ch)
  if (!geo) return

  const ctx = cvs.getContext('2d')!
  const dpr = window.devicePixelRatio || 1
  cvs.width = cw * dpr
  cvs.height = (ch + 40) * dpr
  cvs.style.width = cw + 'px'
  cvs.style.height = (ch + 40) + 'px'
  ctx.scale(dpr, dpr)

  // 背景
  ctx.fillStyle = '#1a1a2e'
  ctx.fillRect(0, 0, cw, ch + 40)

  // 方块
  let placed = 0
  for (const b of props.initData.blocks) {
    const cx = geo.offsetX + (b.x - geo.minX) * geo.cellSize
    const cy = geo.offsetY + (b.z - geo.minZ) * geo.cellSize
    drawBlock(ctx, cx, cy, geo.cellSize, b.expected, b.placed)
    if (b.placed) placed++
  }

  // bot 位置标记（绘制在方块之上）
  drawBotMarkers(ctx, geo)

  // 坐标轴标注
  ctx.fillStyle = '#888888'
  ctx.font = '11px monospace'
  ctx.fillText(`Z: ${geo.minZ} → ${geo.maxZ}  (${geo.maxZ - geo.minZ + 1} 行)`, 10, 16)
  ctx.fillText(`X: ${geo.minX} → ${geo.maxX}  (${geo.maxX - geo.minX + 1} 列)   已放置: ${placed}/${props.initData.blocks.length}`, 10, 32)
  const y0 = props.initData.blocks[0]?.y
  ctx.fillText(`Y 层: ${y0 ?? '?'}`, 10, 48)

  emit('ready')
}

watch(() => props.initData, () => nextTick(render), { deep: true })
watch(() => props.botPositions, () => nextTick(render), { deep: true })

// ── 2D 画布随建造进度实时刷新（每 5s 增量更新已放置格子） ──
let pollTimer: number | undefined

async function pollPlaced() {
  if (!props.taskId) return
  try {
    const { data } = await mapArtApi.getPlacedBlocks(props.taskId)
    const placedKeys = new Set(data.blocks.map((b: any) => `${b.x},${b.z}`))
    const blocks = props.initData?.blocks
    if (!blocks) return
    let changed = false
    for (const b of blocks) {
      if (!b.placed && placedKeys.has(`${b.x},${b.z}`)) {
        b.placed = true
        changed = true
      }
    }
    if (changed) render()
  } catch {
    // 轮询失败静默
  }
}

onMounted(async () => {
  await preloadTextures() // 先加载贴图，再渲染（失败回退纯色不阻塞）
  await nextTick(render)
  pollTimer = window.setInterval(pollPlaced, 5000)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})

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
