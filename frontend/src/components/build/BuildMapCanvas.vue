<template>
  <div class="build2d-wrap">
    <!-- 画布工具栏：缩放 + bot 分区开关（2026-08-14） -->
    <div class="canvas-toolbar">
      <span class="tb-btn" title="缩小" @click="zoomOut">−</span>
      <span class="tb-zoom mono">{{ Math.round(zoom * 100) }}%</span>
      <span class="tb-btn" title="放大" @click="zoomIn">＋</span>
      <span class="tb-btn" title="重置缩放" @click="resetZoom">重置</span>
      <span class="tb-sep"></span>
      <el-switch v-model="showRegions" size="small" />
      <span class="tb-label">bot 分区</span>
    </div>

    <div ref="container" class="build2d-container">
      <div class="canvas-zoom" :style="{ transform: `scale(${zoom})` }">
        <canvas ref="canvas" class="map-canvas" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { mapArtApi } from '@/api/mapArt'

/**
 * 地图画 2D 俯视预览画布（2026-08-14 二期完善）：
 * - 视角：正上方中心往下（俯视），按投影尺寸自适应居中
 * - 方块渲染：使用 item-icons 官方贴图；已放置=正常显示，未放置=半透明虚化
 * - bot 标记：build_bot_status 推送的实时位置 → 按 bot 颜色画圆点 + 名字
 * - bot 分区：每个 bot 的分配区域用其固定颜色矩形框显示（可开关）
 * - 缩放：transform scale + localStorage 持久化（下次进入保持）
 */

export interface BotMarker {
  bot_id: string
  bot_name?: string
  state?: string
  position?: { x: number; y: number; z: number } | null
  color?: string
  region?: { x_start: number; x_end: number; z_start: number; z_end: number } | null
}

const props = defineProps<{
  taskId: string
  materials?: { item_id: string; display_name: string; placed: number; required: number }[]
  initData?: { blocks: { x: number; y: number; z: number; expected: string; placed: boolean }[]; origin: { x: number; y: number; z: number }; size: { x: number; z: number } } | null
  botPositions?: BotMarker[]
}>()

const emit = defineEmits<{ ready: [] }>()

const container = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()

// ── 缩放（持久化到 localStorage，下次进入保持） ──
const ZOOM_KEY = 'vmtools-mapart-zoom'
const MIN_ZOOM = 0.5
const MAX_ZOOM = 2.5
const zoom = ref(parseFloat(localStorage.getItem(ZOOM_KEY) || '1') || 1)
function clampZoom(v: number): number { return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v)) }
zoom.value = clampZoom(zoom.value)
watch(zoom, (v) => {
  try { localStorage.setItem(ZOOM_KEY, String(clampZoom(v))) } catch { /* 隐私模式 */ }
})
function zoomIn() { zoom.value = clampZoom(Math.round((zoom.value + 0.1) * 10) / 10) }
function zoomOut() { zoom.value = clampZoom(Math.round((zoom.value - 0.1) * 10) / 10) }
function resetZoom() { zoom.value = 1 }

// ── bot 分区区域框开关（默认开） ──
const showRegions = ref(true)

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
    img.onerror = () => resolve()
    img.src = `/static/item-icons/${pure}.png`
  })
  textureLoading.set(itemId, p)
  return p
}

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

/** 世界/相对坐标 → 画布像素 */
function toCanvas(geo: Geo, wx: number, wz: number): { x: number; y: number } {
  return { x: geo.offsetX + (wx - geo.minX) * geo.cellSize, y: geo.offsetY + (wz - geo.minZ) * geo.cellSize }
}

function drawBlock(ctx: CanvasRenderingContext2D, cx: number, cy: number, cs: number, blockId: string, placed: boolean) {
  const clean = blockId.split('[')[0]
  const img = textureCache.get(clean) ?? textureCache.get(blockId)
  if (img) {
    ctx.globalAlpha = placed ? 1 : 0.4
    ctx.drawImage(img, cx, cy, cs, cs)
    ctx.globalAlpha = 1
    if (!placed) {
      ctx.strokeStyle = 'rgba(255,255,255,0.25)'
      ctx.lineWidth = 0.5
      ctx.strokeRect(cx + 0.5, cy + 0.5, cs - 1, cs - 1)
    }
  } else {
    ctx.fillStyle = placed ? blockColor(blockId) : '#444444'
    ctx.fillRect(cx, cy, cs, cs)
    if (!placed) {
      ctx.strokeStyle = '#666666'
      ctx.lineWidth = 0.5
      ctx.strokeRect(cx, cy, cs, cs)
    }
  }
}

/** bot 位置点 */
function drawBotMarkers(ctx: CanvasRenderingContext2D, geo: Geo) {
  const bots = props.botPositions || []
  if (!bots.length) return
  const r = Math.max(4, Math.round(geo.cellSize * 0.35))
  for (const b of bots) {
    if (!b.position || b.position.x == null || b.position.z == null) continue
    const { x: cx, y: cy } = toCanvas(geo, b.position.x, b.position.z)
    const color = b.color || stableColor(b.bot_id)
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
    ctx.font = '10px monospace'
    ctx.fillStyle = '#ffffff'
    ctx.shadowColor = 'rgba(0,0,0,0.9)'
    ctx.shadowBlur = 3
    ctx.fillText(b.bot_name || b.bot_id, cx + r + 2, cy + 4)
    ctx.shadowBlur = 0
  }
}

/** bot 分配区域框（固定颜色矩形 + 名字标注） */
function drawRegions(ctx: CanvasRenderingContext2D, geo: Geo) {
  if (!showRegions.value) return
  const bots = props.botPositions || []
  for (const b of bots) {
    if (!b.region || b.region.x_start == null) continue
    const { x_start, x_end, z_start, z_end } = b.region
    const p1 = toCanvas(geo, x_start, z_start)
    const p2 = toCanvas(geo, x_end, z_end)
    const w = p2.x - p1.x + geo.cellSize
    const h = p2.y - p1.y + geo.cellSize
    const color = b.color || stableColor(b.bot_id)
    ctx.save()
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.strokeRect(p1.x - 2, p1.y - 2, w + 4, h + 4)
    ctx.setLineDash([])
    // 区域角标：bot 名
    ctx.font = 'bold 11px monospace'
    const label = b.bot_name || b.bot_id
    const tw = ctx.measureText(label).width
    ctx.fillStyle = color
    ctx.globalAlpha = 0.85
    ctx.fillRect(p1.x - 2, p1.y - 2, tw + 8, 15)
    ctx.globalAlpha = 1
    ctx.fillStyle = '#ffffff'
    ctx.fillText(label, p1.x + 2, p1.y + 10)
    ctx.restore()
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

  ctx.fillStyle = '#1a1a2e'
  ctx.fillRect(0, 0, cw, ch + 40)

  let placed = 0
  for (const b of props.initData.blocks) {
    const { x: cx, y: cy } = toCanvas(geo, b.x, b.z)
    drawBlock(ctx, cx, cy, geo.cellSize, b.expected, b.placed)
    if (b.placed) placed++
  }

  // 区域框（画在方块之上、位置点之下）
  drawRegions(ctx, geo)
  // bot 位置点
  drawBotMarkers(ctx, geo)

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
watch(showRegions, () => nextTick(render))

// ── 建造进度实时刷新（每 5s 增量更新已放置格子） ──
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
  await preloadTextures()
  await nextTick(render)
  pollTimer = window.setInterval(pollPlaced, 5000)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})

defineExpose({ refresh: render })
</script>

<style scoped>
.build2d-wrap { display: flex; flex-direction: column; gap: 6px; }
.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  width: fit-content;
}
.tb-btn {
  cursor: pointer;
  user-select: none;
  padding: 1px 8px;
  font-size: 15px;
  line-height: 20px;
  border-radius: 4px;
  color: var(--text-secondary);
}
.tb-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.tb-zoom { font-size: 12px; color: var(--text-secondary); min-width: 42px; text-align: center; }
.tb-sep { width: 1px; height: 16px; background: var(--border-subtle); margin: 0 4px; }
.tb-label { font-size: 12px; color: var(--text-muted); }
.build2d-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
  background: #1a1a2e;
  border-radius: 8px;
  overflow: auto;
}
.canvas-zoom {
  transform-origin: top left;
  width: 100%;
  height: 100%;
}
.map-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
</style>