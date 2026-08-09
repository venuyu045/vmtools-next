<template>
  <div
    ref="base"
    class="joystick"
    :style="{ width: size + 'px', height: size + 'px' }"
    @pointerdown="onDown"
    @pointermove="onMove"
    @pointerup="onUp"
    @pointercancel="onUp"
    @pointerleave="onLeave"
  >
    <div class="joystick-ring" />
    <div class="joystick-knob" :style="{ transform: `translate(${knobX}px, ${knobY}px)` }" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{ size?: number }>(), { size: 110 })
const emit = defineEmits<{
  /** dx/dy ∈ [-1, 1]，归一化向量 */
  move: [dx: number, dy: number]
  end: []
}>()

const base = ref<HTMLElement | null>(null)
const knobX = ref(0)
const knobY = ref(0)
let active = false

function onDown(e: PointerEvent) {
  active = true
  try { base.value?.setPointerCapture(e.pointerId) } catch { /* ignore */ }
  handleMove(e)
}

function onMove(e: PointerEvent) {
  if (!active) return
  handleMove(e)
}

function handleMove(e: PointerEvent) {
  const el = base.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  let dx = (e.clientX - cx) / (rect.width / 2)
  let dy = (e.clientY - cy) / (rect.height / 2)
  const len = Math.hypot(dx, dy)
  if (len > 1) { dx /= len; dy /= len }  // 圆形范围约束
  knobX.value = dx * (rect.width / 2) * 0.65
  knobY.value = dy * (rect.height / 2) * 0.65
  emit('move', dx, dy)
}

function onUp() {
  if (!active) return
  active = false
  knobX.value = 0
  knobY.value = 0
  emit('end')
}

function onLeave(e: PointerEvent) {
  // 未捕获指针时离开才结束；已捕获（拖拽中）不结束，避免拖动出界中断
  if (!active || !base.value?.hasPointerCapture(e.pointerId)) onUp()
}
</script>

<style scoped>
.joystick {
  position: relative;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.15);
  touch-action: none;
  user-select: none;
  cursor: grab;
}
.joystick:active { cursor: grabbing; }
.joystick-ring {
  position: absolute;
  inset: 14%;
  border-radius: 50%;
  border: 1px dashed rgba(255, 255, 255, 0.18);
  pointer-events: none;
}
.joystick-knob {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 42px;
  height: 42px;
  margin-left: -21px;
  margin-top: -21px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #fff 0%, #d97757 55%, #a8542f 100%);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  pointer-events: none;
  transition: transform 0.05s linear;
}
</style>