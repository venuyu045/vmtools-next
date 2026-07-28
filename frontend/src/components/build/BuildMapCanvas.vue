<template>
  <div ref="container" class="build-map-container">
    <canvas ref="canvas" class="map-canvas" />

    <!-- Legend overlay -->
    <div v-if="materials?.length" class="legend-overlay">
      <div v-for="m in materials" :key="m.item_id" class="legend-item">
        <span class="color-dot" :style="{ background: toHex(m.item_id) }" />
        <span class="label">{{ m.display_name }}</span>
        <span class="count">{{ m.placed }}/{{ m.required }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { BuildMapScene, type MapInitData, type BlockState, type BotMarker } from './BuildMapScene'
import { useSocketIO } from '@/composables/useSocketIO'

const props = defineProps<{
  taskId: string
  materials?: { item_id: string; display_name: string; placed: number; required: number }[]
}>()

const emit = defineEmits<{ ready: [] }>()

const container = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()
let scene: BuildMapScene | null = null

const { on: sockOn, emit: sockEmit, connected } = useSocketIO()
const isConnected = computed(() => connected())

// Watch for socket connection, then join room
watch(isConnected, (yes) => {
  if (yes && props.taskId) {
    sockEmit('build_map_join', { task_id: props.taskId })
  }
})

onMounted(() => {
  if (!canvas.value) return
  scene = new BuildMapScene(canvas.value)

  // Socket event handlers
  sockOn('build_map_init', (data: MapInitData) => {
    if (data.task_id !== props.taskId) return
    scene!.initialize(data)
    emit('ready')
  })

  sockOn('build_blocks_changed', (data: { task_id: string; changes: { x: number; y: number; z: number; status: string; actual: string }[] }) => {
    if (data.task_id !== props.taskId) return
    for (const c of data.changes) {
      if (c.status === 'placed') {
        scene!.updateBlockPlaced(c.x, c.y, c.z, c.actual)
      }
    }
  })

  sockOn('build_bot_moved', (data: { task_id: string; bots: { bot_id: string; x: number; y: number; z: number }[] }) => {
    if (data.task_id !== props.taskId) return
    for (const b of data.bots) {
      scene!.updateBotPosition(b.bot_id, b.x, b.y, b.z)
    }
  })

  // Join room (in case socket already connected)
  if (connected()) {
    sockEmit('build_map_join', { task_id: props.taskId })
  }

  // Start render loop
  scene.animate()

  // Resize observer
  const el = container.value!
  const ro = new ResizeObserver(() => {
    const { clientWidth: w, clientHeight: h } = el
    scene!.onResize(w, h)
  })
  ro.observe(el)

  onUnmounted(() => {
    ro.disconnect()
    scene?.dispose()
    sockEmit('build_map_leave', { task_id: props.taskId })
  })
})

// ---- Color helper ----
const WOOL_COLORS: Record<string, string> = {
  'minecraft:white_wool': '#FFFFFF', 'minecraft:orange_wool': '#F9801D',
  'minecraft:magenta_wool': '#C74EBD', 'minecraft:light_blue_wool': '#3AB3DA',
  'minecraft:yellow_wool': '#FED83D', 'minecraft:lime_wool': '#80C71F',
  'minecraft:pink_wool': '#F38BAA', 'minecraft:gray_wool': '#474F52',
  'minecraft:light_gray_wool': '#9D9D97', 'minecraft:cyan_wool': '#169C9D',
  'minecraft:purple_wool': '#8932B8', 'minecraft:blue_wool': '#3C44AA',
  'minecraft:brown_wool': '#835432', 'minecraft:green_wool': '#5E7C16',
  'minecraft:red_wool': '#B02E26', 'minecraft:black_wool': '#1D1D21',
}
function toHex(itemId: string): string {
  return WOOL_COLORS[itemId] ?? '#888888'
}
</script>

<style scoped>
.build-map-container {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 500px;
  background: #1a1a2e;
  border-radius: 8px;
  overflow: hidden;
}
.map-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
.legend-overlay {
  position: absolute;
  top: 12px;
  right: 12px;
  background: rgba(0, 0, 0, 0.7);
  border-radius: 8px;
  padding: 10px 14px;
  max-height: 60%;
  overflow-y: auto;
  font-size: 12px;
  color: #ccc;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
}
.color-dot {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
}
.label {
  flex: 1;
  white-space: nowrap;
}
.count {
  color: #888;
  font-variant-numeric: tabular-nums;
}
</style>
