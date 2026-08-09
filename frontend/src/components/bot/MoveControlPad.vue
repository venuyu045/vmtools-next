<template>
  <div class="move-pad">
    <div class="pad-left">
      <!-- 十字方向键：长按持续移动，松开停止 -->
      <div class="group">
        <div class="group-label">移动</div>
        <div class="dpad">
          <button
            class="dbtn up"
            @pointerdown="down('forward')"
            @pointerup="up('forward')"
            @pointercancel="up('forward')"
            @pointerleave="up('forward')"
          >▲</button>
          <button
            class="dbtn left"
            @pointerdown="down('left')"
            @pointerup="up('left')"
            @pointercancel="up('left')"
            @pointerleave="up('left')"
          >◀</button>
          <button
            class="dbtn down"
            @pointerdown="down('back')"
            @pointerup="up('back')"
            @pointercancel="up('back')"
            @pointerleave="up('back')"
          >▼</button>
          <button
            class="dbtn right"
            @pointerdown="down('right')"
            @pointerup="up('right')"
            @pointercancel="up('right')"
            @pointerleave="up('right')"
          >▶</button>
        </div>
      </div>
      <div class="group">
        <div class="group-label">动作</div>
        <div class="act-btns">
          <button class="abtn sneak" :class="{ on: sneaking }" @click="toggleSneak">蹲</button>
          <button class="abtn jump" @click="doJump">跳</button>
        </div>
      </div>
    </div>

    <div class="pad-right">
      <div class="group group-joy">
        <div class="group-label">视角</div>
        <Joystick :size="120" @move="onLookMove" @end="onLookEnd" />
        <div class="joy-label">拖动摇杆 · 左滑左转 / 右滑右转</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { botApi } from '@/api/bot'
import Joystick from './Joystick.vue'

const props = defineProps<{ botId: string }>()

const sneaking = ref(false)
// 视角基准（弧度），look 接口成功后以服务器回读为准
let baseYaw = 0
let basePitch = 0
let lookPending: { yaw: number; pitch: number } | null = null
let lookTimer: number | undefined

// ── 移动方向键 ──
function down(direction: string) {
  botApi.control(props.botId, { direction, state: true }).catch(() => {})
}
function up(direction: string) {
  botApi.control(props.botId, { direction, state: false }).catch(() => {})
}

function doJump() {
  botApi.jump(props.botId).catch(() => {})
}

function toggleSneak() {
  sneaking.value = !sneaking.value
  botApi.sneak(props.botId, sneaking.value).catch(() => {})
}

// ── 视角摇杆：增量累计 → 节流发送 look → 回读实际角度修正基准 ──
// 方向约定：右滑 → 视角右转（yaw 增大 = 顺时针）；上滑 → 视角上抬（pitch 减小）。
// 注意：实际体验中摇杆水平方向与 bot yaw 相反，这里取反（用户反馈修复）。
function onLookMove(dx: number, dy: number) {
  const YAW_SPEED = 0.09   // 每帧水平增量（弧度）
  const PITCH_SPEED = 0.09
  baseYaw -= dx * YAW_SPEED
  basePitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, basePitch + dy * PITCH_SPEED))
  lookPending = { yaw: baseYaw, pitch: basePitch }
  if (lookTimer === undefined) {
    lookTimer = window.setInterval(flushLook, 80)
  }
}

function flushLook() {
  if (!lookPending) { stopLookTimer(); return }
  const { yaw, pitch } = lookPending
  lookPending = null
  botApi.look(props.botId, { yaw, pitch })
    .then((resp: any) => {
      // 以服务器回读的实体实际朝向为基准，防止累计漂移
      const r = resp?.data?.result
      if (r && typeof r.yaw === 'number') {
        baseYaw = r.yaw
        if (typeof r.pitch === 'number') basePitch = r.pitch
      }
    })
    .catch(() => {})
}

function onLookEnd() {
  stopLookTimer()
}

function stopLookTimer() {
  if (lookTimer !== undefined) {
    window.clearInterval(lookTimer)
    lookTimer = undefined
  }
  lookPending = null
}

// ── 初始化：获取当前朝向作为视角基准 ──
function loadBase() {
  botApi.getState(props.botId)
    .then((resp: any) => {
      const r = resp?.data?.result || {}
      if (typeof r.yaw === 'number') baseYaw = r.yaw
      if (typeof r.pitch === 'number') basePitch = r.pitch
    })
    .catch(() => {})
}

onBeforeUnmount(stopLookTimer)
loadBase()
</script>

<style scoped>
.move-pad {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 18px;
  margin-bottom: 12px;
  background: var(--bg-card, #1a1a1a);
  border: 1px solid var(--border-subtle, #333);
  border-radius: var(--radius-md, 8px);
  user-select: none;
  flex-wrap: wrap;
}

.pad-left {
  display: flex;
  align-items: flex-start;
  gap: 24px;
}

.group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.group-label {
  font-size: 11px;
  color: var(--text-muted, #888);
  letter-spacing: 2px;
}

.dpad {
  display: grid;
  grid-template-columns: repeat(3, 46px);
  grid-template-rows: repeat(2, 46px);
  gap: 4px;
}
.dbtn {
  width: 46px;
  height: 46px;
  border: 1px solid var(--border-default, #555);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary, #fff);
  font-size: 16px;
  cursor: pointer;
  touch-action: none;
  user-select: none;
  transition: transform 0.08s, background 0.08s;
}
.dbtn:active {
  background: var(--accent, #d97757);
  color: #fff;
  transform: scale(0.92);
}
.dbtn.up { grid-column: 2; grid-row: 1; }
.dbtn.left { grid-column: 1; grid-row: 2; }
.dbtn.down { grid-column: 2; grid-row: 2; }
.dbtn.right { grid-column: 3; grid-row: 2; }

.act-btns {
  display: flex;
  flex-direction: row;
  gap: 8px;
}
.abtn {
  width: 54px;
  height: 44px;
  border: 1px solid var(--border-default, #555);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary, #fff);
  font-size: 15px;
  cursor: pointer;
  touch-action: none;
  user-select: none;
  transition: transform 0.08s, background 0.08s;
}
.abtn:active { transform: scale(0.94); }
.abtn.sneak.on {
  background: var(--accent, #d97757);
  color: #fff;
  box-shadow: 0 0 8px rgba(217, 119, 87, 0.4);
}
.abtn.jump { background: rgba(217, 119, 87, 0.22); border-color: rgba(217, 119, 87, 0.5); }
.abtn.jump:active { background: var(--accent, #d97757); }

.pad-right {
  display: flex;
}
.group-joy {
  gap: 8px;
}
.joy-label {
  font-size: 11px;
  color: var(--text-muted, #888);
  text-align: center;
  max-width: 140px;
}
</style>