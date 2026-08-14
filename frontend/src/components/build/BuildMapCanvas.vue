<template>
  <div class="build2d-wrap">
    <!-- 画布工具栏：缩放 + bot 分区开关 -->
    <div class="canvas-toolbar">
      <span class="tb-btn" title="缩小" @click="zoomOut">−</span>
      <span class="tb-zoom mono">{{ Math.round(zoom * 100) }}%</span>
      <span class="tb-btn" title="放大" @click="zoomIn">＋</span>
      <span class="tb-btn" title="重置缩放" @click="resetZoom">重置</span>
      <span class="tb-sep"></span>
      <el-switch v-model="showRegions" size="small" />
      <span class="tb-label">bot 分区</span>
      <span class="tb-hint" v-if="zoom > 1">放大后可拖动画布查看任意位置</span>
    </div>

    <!-- 容器：固定区域可滚动；stage 撑开滚动范围；canvas transform 缩放（不重绘） -->
    <div ref="container" class="build2d-container">
      <div class="canvas-stage" :style="{ width: stageW + 'px', height: stageH + 'px' }">
        <canvas
          ref="canvas"
          class="map-canvas"
          :style="{ transform: `scale(${zoom})`, transformOrigin: 'top left' }"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { mapArtApi } from '@/api/mapArt'

/**
 * 地图画 2D 俯视预览画布（2026-08-14 三期视图重做）：
 * - 画布物理尺寸固定（容器尺寸算一次，ResizeObserver 更新），render 不重设尺寸
 * - 缩放：canvas CSS transform:scale（纯视觉，不重绘）；stage 撑开 = 尺寸×zoom → 滚动条正确
 * - 拖拽平移：放大后按住拖动画布查看任意位置
 * - bot 分区开关只重绘内容，尺寸不变 → 无跳动
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

// ── 缩放（持久化 localStorage） ──
const ZOOM_KEY = 'vmtools-mapart-zoom'
const MIN_ZOOM = 0.5
const MAX_ZOOM = 3
const zoom = ref(clampZoom(parseFloat(localStorage.getItem(ZOOM_KEY) || '1') || 1))
function clampZoom(v: number): number { return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v)) }
watch(zoom, (v) => { try { localStorage.setItem(ZOOM_KEY, String(clampZoom(v))) } catch { /* 隐私模式 */ } })
function zoomIn() { zoom.value = clampZoom(Math.round((zoom.value + 0.1) * 10) / 10) }
function zoomOut() { zoom.value = clampZoom(Math.round((zoom.value - 0.1) * 10) / 10) }
function resetZoom() { zoom.value = 1 }

// ── bot 分区开关（默认开） ──
const showRegions = ref(true)

// ── 画布物理尺寸（固定，px；由容器尺寸算一次） ──
const cw = ref(0)
const ch = ref(0)
// stage 撑开层尺寸 = 画布尺寸 × zoom（撑开滚动范围）
const stageW = computed(() => Math.round(cw.value * zoom.value))
const stageH = computed(() => Math.round(ch.value * zoom.value))

// ── 拖拽平移 + 双指捏合缩放 ──
// 2026-08-14：平板「电脑版网页」触摸走 Pointer Events（Edge 电脑模式/触屏本），
// 仅监听 touch 事件无效。统一用 pointer 事件：单指=拖拽平移，双指=捏合缩放。
let dragging = false
let dragStartX = 0
let dragStartY = 0
let scrollStartLeft = 0
let scrollStartTop = 0
const activePointers = new Map<number, { x: number; y: number }>()
let pinchStartDist = 0
let pinchStartZoom = 1
function onPointerDown(e: PointerEvent) {
  activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (activePointers.size >= 2) {
    // 双指 → 进入捏合缩放，取消拖拽
    dragging = false
    const pts = [...activePointers.values()]
    pinchStartDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)
    pinchStartZoom = zoom.value
    return
  }
  // 单指 → 拖拽平移
  dragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  scrollStartLeft = container.value?.scrollLeft ?? 0
  scrollStartTop = container.value?.scrollTop ?? 0
  container.value?.setPointerCapture?.(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (!activePointers.has(e.pointerId)) return
  activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (activePointers.size >= 2) {
    // 捏合缩放：按两指距离比例更新 zoom（0.5x~3x，0.1 步进）
    const pts = [...activePointers.values()]
    const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)
    if (pinchStartDist > 0) {
      const next = clampZoom(Math.round(pinchStartZoom * (dist / pinchStartDist) * 10) / 10)
      if (next !== zoom.value) zoom.value = next
    }
    return
  }
  if (dragging && container.value) {
    container.value.scrollLeft = scrollStartLeft - (e.clientX - dragStartX)
    container.value.scrollTop = scrollStartTop - (e.clientY - dragStartY)
  }
}
function onPointerUp(e: PointerEvent) {
  activePointers.delete(e.pointerId)
  if (activePointers.size === 1) {
    // 抬一指剩一指：从剩余手指位置重新开始拖拽
    const [p] = [...activePointers.values()]
    dragStartX = p.x
    dragStartY = p.y
    scrollStartLeft = container.value?.scrollLeft ?? 0
    scrollStartTop = container.value?.scrollTop ?? 0
    dragging = true
  } else if (activePointers.size === 0) {
    dragging = false
  }
}

// ── 贴图缓存 ──
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

// ── 颜色 ──
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
function computeGeo(): Geo | null {
  const blocks = props.initData?.blocks
  if (!blocks?.length || cw.value <= 0) return null
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
  for (const b of blocks) {
    minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x)
    minZ = Math.min(minZ, b.z); maxZ = Math.max(maxZ, b.z)
  }
  const cols = maxX - minX + 1
  const rows = maxZ - minZ + 1
  const cellSize = Math.max(4, Math.min(40, Math.floor(Math.min(cw.value / cols, ch.value / rows))))
  const totalW = cols * cellSize
  const totalH = rows * cellSize
  return {
    minX, maxX, minZ, maxZ, cellSize,
    offsetX: Math.floor((cw.value - totalW) / 2),
    offsetY: Math.floor((ch.value - totalH) / 2),
  }
}
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

function drawBotMarkers(ctx: CanvasRenderingContext2D, geo: Geo) {
  const bots = props.botPositions || []
  if (!bots.length) return
  const r = Math.max(4, Math.round(geo.cellSize * 0.35))
  for (const b of bots) {
    if (!b.position || b.position.x == null || b.position.z == null) continue
    const { x: cx, y: cy } = toCanvas(geo, b.position.x, b.position.z)
    const color = b.color || stableColor(b.bot_id)
    ctx.beginPath(); ctx.arc(cx, cy, r + 2, 0, Math.PI * 2); ctx.fillStyle = 'rgba(255,255,255,0.9)'; ctx.fill()
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill()
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.stroke()
    ctx.font = '10px monospace'; ctx.fillStyle = '#ffffff'
    ctx.shadowColor = 'rgba(0,0,0,0.9)'; ctx.shadowBlur = 3
    ctx.fillText(b.bot_name || b.bot_id, cx + r + 2, cy + 4)
    ctx.shadowBlur = 0
  }
}

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
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash([6, 4])
    ctx.strokeRect(p1.x - 2, p1.y - 2, w + 4, h + 4)
    ctx.setLineDash([])
    ctx.font = 'bold 11px monospace'
    const label = b.bot_name || b.bot_id
    const tw = ctx.measureText(label).width
    ctx.fillStyle = color; ctx.globalAlpha = 0.85
    ctx.fillRect(p1.x - 2, p1.y - 2, tw + 8, 15)
    ctx.globalAlpha = 1; ctx.fillStyle = '#ffffff'
    ctx.fillText(label, p1.x + 2, p1.y + 10)
    ctx.restore()
  }
}

/** 重绘画布内容（canvas 物理尺寸不变，不引起布局跳动） */
function render() {
  const cvs = canvas.value
  if (!cvs || !props.initData?.blocks?.length || cw.value <= 0 || ch.value <= 0) return
  const geo = computeGeo()
  if (!geo) return

  const ctx = cvs.getContext('2d')!
  const dpr = window.devicePixelRatio || 1
  // 物理尺寸固定：只在尺寸变化时由 initSize 设置；这里不重设 width/height（防跳动/清空闪烁）
  if (cvs.width !== Math.round(cw.value * dpr) || cvs.height !== Math.round(ch.value * dpr)) {
    cvs.width = Math.round(cw.value * dpr)
    cvs.height = Math.round(ch.value * dpr)
  }
  // CSS 尺寸 = 物理尺寸（px）；缩放由 stage + transform 处理，避免 CSS 拉伸与 scale 双重缩放
  cvs.style.width = cw.value + 'px'
  cvs.style.height = ch.value + 'px'
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  ctx.fillStyle = '#1a1a2e'
  ctx.fillRect(0, 0, cw.value, ch.value)

  let placed = 0
  for (const b of props.initData.blocks) {
    const { x: cx, y: cy } = toCanvas(geo, b.x, b.z)
    drawBlock(ctx, cx, cy, geo.cellSize, b.expected, b.placed)
    if (b.placed) placed++
  }
  drawRegions(ctx, geo)
  drawBotMarkers(ctx, geo)

  ctx.fillStyle = '#888888'
  ctx.font = '11px monospace'
  ctx.fillText(`Z: ${geo.minZ} → ${geo.maxZ}`, 10, 16)
  ctx.fillText(`X: ${geo.minX} → ${geo.maxX}  已放置: ${placed}/${props.initData.blocks.length}`, 10, 32)

  emit('ready')
}

/** 根据容器尺寸初始化画布物理尺寸（ResizeObserver 调用） */
function initSize() {
  const el = container.value
  if (!el) return
  const w = el.clientWidth
  const h = el.clientHeight
  if (w <= 0 || h <= 0) return
  if (cw.value !== w || ch.value !== h) {
    cw.value = w
    ch.value = h
    nextTick(render)
  }
}

watch(() => props.initData, () => nextTick(render), { deep: true })
watch(() => props.botPositions, () => nextTick(render), { deep: true })
watch(showRegions, () => nextTick(render))
// zoom 变化：仅 stage 尺寸 + transform 自动更新（computed），不重绘

// ── 建造进度实时刷新（5s 增量） ──
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
      if (!b.placed && placedKeys.has(`${b.x},${b.z}`)) { b.placed = true; changed = true }
    }
    if (changed) render()
  } catch { /* 静默 */ }
}

let resizeObserver: ResizeObserver | null = null
onMounted(async () => {
  await preloadTextures()
  initSize()
  resizeObserver = new ResizeObserver(() => initSize())
  if (container.value) resizeObserver.observe(container.value)
  pollTimer = window.setInterval(pollPlaced, 5000)
  // 拖拽平移
  container.value?.addEventListener('pointerdown', onPointerDown)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
})
onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  resizeObserver?.disconnect()
  container.value?.removeEventListener('pointerdown', onPointerDown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})

defineExpose({ refresh: render })
</script>

<style scoped>
.build2d-wrap {
  /* 2026-08-14：预览视图固定大小区域——高度 = 工具栏 + 固定 460px 画布区，
     不再 flex 撑满/被压缩；宽度自适应列宽；画布内部滚动。 */
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.canvas-toolbar {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px; background: var(--bg-card);
  border: 1px solid var(--border-subtle); border-radius: 6px; width: fit-content;
}
.tb-btn { cursor: pointer; user-select: none; padding: 1px 8px; font-size: 15px; line-height: 20px; border-radius: 4px; color: var(--text-secondary); }
.tb-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.tb-zoom { font-size: 12px; color: var(--text-secondary); min-width: 42px; text-align: center; }
.tb-sep { width: 1px; height: 16px; background: var(--border-subtle); margin: 0 4px; }
.tb-label { font-size: 12px; color: var(--text-muted); }
.tb-hint { font-size: 11px; color: var(--text-muted); margin-left: 4px; }
.build2d-container {
  /* 2026-08-14：固定大小预览区域（高度 460px，宽度 100%）——稳定不跳动，
     缩放只改 stage transform，容器滚动范围由 stage 撑开 */
  flex: none;
  width: 100%;
  height: 460px;
  background: #1a1a2e;
  border-radius: 8px;
  overflow: auto;
  cursor: grab;
  /* 2026-08-14：触控手势（单指拖拽平移/双指捏合缩放）由 JS pointer 事件接管，
     阻止浏览器默认的页面级滚动/缩放手势；鼠标滚轮/滚动条不受影响 */
  touch-action: none;
}
.build2d-container:active { cursor: grabbing; }
.canvas-stage { position: relative; }
.map-canvas { display: block; }
</style>