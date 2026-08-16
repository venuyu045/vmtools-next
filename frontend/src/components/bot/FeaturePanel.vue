<template>
  <div class="feature-panel">
    <div class="feature-head">
      <span class="feature-title">功能（MF 独有）</span>
      <span class="feature-badge">按 bot 独立开关</span>
    </div>

    <!-- ── 永昼：自动睡觉跳过黑夜 ── -->
    <div class="feature-card">
      <div class="card-head">
        <div class="card-title">
          🌞 永昼 · 自动睡觉跳过黑夜
          <el-tag size="small" :type="enabled ? 'success' : 'info'" class="state-tag">
            {{ enabled ? '已启用' : '已关闭' }}
          </el-tag>
          <el-tag v-if="pluginEnabled === false" size="small" type="warning" plain class="global-tag">
            全局已禁用
          </el-tag>
        </div>
        <el-switch
          :model-value="enabled"
          :loading="toggling"
          :disabled="toggling"
          @change="(val: string | number | boolean) => handleToggle(!!val)"
        />
      </div>
      <div class="card-desc">
        夜晚（约 18:20 起）且 bot 空闲时，自动走到下方配置的「睡觉点」睡觉，
        服务器一人睡即跳过黑夜 → 天亮自动醒来 → 可选返回原位置。实现服务器永昼。
      </div>

      <!-- 状态行 -->
      <div class="status-grid" v-if="status">
        <div class="status-item">
          <span class="status-label">服务器时间</span>
          <span class="status-value mono">{{ mcClock }}<span class="status-sub">{{ dayInfo }}</span></span>
        </div>
        <div class="status-item">
          <span class="status-label">睡觉状态</span>
          <span class="status-value" :class="{ sleeping: timeStatus?.is_sleeping }">
            {{ timeStatus?.is_sleeping ? '😴 睡觉中' : '醒着' }}
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">维度</span>
          <span class="status-value mono">{{ dimLabel }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">忙碌（跳过睡觉）</span>
          <span class="status-value" :class="{ busy: !!status.busy }">
            {{ status.busy ? busyLabel : '空闲' }}
          </span>
        </div>
      </div>

      <!-- 最近一次结果 -->
      <div v-if="status?.last_result" class="last-result">
        <span class="result-label">最近一次：</span>
        <span class="result-reason" :class="status.last_result.ok ? 'ok' : 'fail'">
          {{ status.last_result.ok ? '✅ ' : '⛔ ' }}{{ status.last_result.reason || '—' }}
        </span>
        <span class="result-time mono">{{ fmtTime(status.last_result.at) }}</span>
      </div>
      <div v-if="timeStatus && timeStatus.do_daylight_cycle === false" class="warn-line">
        ⚠️ 服务器已关闭昼夜循环（doDaylightCycle=false），睡觉不会跳过时间，本功能无效。
      </div>

      <!-- 睡觉点配置 -->
      <div class="point-row">
        <span class="point-label">睡觉点（床的坐标）</span>
        <el-input-number v-model="point.x" :step="1" controls-position="right" class="point-input" placeholder="X" />
        <el-input-number v-model="point.y" :step="1" controls-position="right" class="point-input" placeholder="Y" />
        <el-input-number v-model="point.z" :step="1" controls-position="right" class="point-input" placeholder="Z" />
        <button class="pixel-btn outline mini" :disabled="!pointValid" @click="savePoint">保存</button>
        <button class="pixel-btn outline mini" :disabled="!status?.sleep_point" @click="clearPoint">清除</button>
      </div>
      <div v-if="!status?.sleep_point" class="point-hint">
        尚未配置睡觉点：先在游戏里把一张床放到固定位置，然后把床的方块坐标填到这里。
      </div>

      <div class="card-actions">
        <button class="pixel-btn outline" :disabled="!status?.sleep_point || sleepingNow" @click="sleepNow">
          {{ sleepingNow ? '睡觉中…' : '立即睡一次（测试）' }}
        </button>
      </div>
    </div>

    <div v-if="loading" v-loading="loading" class="empty-text mono">加载中…</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { botApi } from '@/api/bot'
import { pluginApi } from '@/api/plugin'
import { errMsg } from '@/utils/error'

const props = defineProps<{ botId: string }>()

const loading = ref(false)
const toggling = ref(false)
const sleepingNow = ref(false)
const status = ref<any>(null)
const point = reactive({ x: 0, y: 0, z: 0 })
let timer: number | undefined

const enabled = computed(() => !!status.value?.enabled)
const pluginEnabled = computed(() => status.value?.plugin_enabled)
const timeStatus = computed(() => status.value?.time_status || null)
const pointValid = computed(() => point.x !== 0 || point.y !== 0 || point.z !== 0)

/** MC 时间 timeOfDay（0=6:00）→ 游戏时钟 HH:mm */
const mcClock = computed(() => {
  const tod = timeStatus.value?.time_of_day
  if (tod == null) return '—'
  const hours = Math.floor(tod / 1000 + 6) % 24
  const mins = Math.floor(((tod % 1000) / 1000) * 60)
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
})
const dayInfo = computed(() => {
  const t = timeStatus.value
  if (!t) return ''
  return t.is_day ? ' · 白天' : ' · 夜晚'
})
const dimLabel = computed(() => {
  const d = timeStatus.value?.dimension
  if (!d) return '—'
  if (d === 'overworld' || d === 'minecraft:overworld') return '主世界'
  if (d === 'the_nether' || d === 'minecraft:the_nether') return '下界'
  if (d === 'the_end' || d === 'minecraft:the_end') return '末地'
  return d
})
const busyLabel = computed(() => {
  const s = status.value
  if (s?.combat_mode) return `战斗中（${s.combat_mode}）`
  if (s?.current_task) return `${s.current_task.name || '任务中'}`
  return '忙碌'
})

function fmtTime(iso?: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return ''
    const p = (n: number) => String(n).padStart(2, '0')
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  } catch {
    return ''
  }
}

async function load() {
  if (!props.botId) return
  loading.value = true
  try {
    const resp = await botApi.sleepStatus(props.botId)
    status.value = resp.data
    const sp = resp.data?.sleep_point
    if (sp) {
      point.x = sp.x; point.y = sp.y; point.z = sp.z
    }
  } catch (e: any) {
    // 插件未加载等 → 显示错误但不刷屏（轮询静默）
    if (e?.response?.status !== 404) {
      status.value = null
    }
  } finally {
    loading.value = false
  }
}

async function handleToggle(val: boolean) {
  if (toggling.value) return
  toggling.value = true
  try {
    if (val) {
      await pluginApi.enablePluginForBot('auto_sleep', props.botId)
    } else {
      await pluginApi.disablePluginForBot('auto_sleep', props.botId)
    }
    if (status.value) status.value.enabled = val
    ElMessage.success(`永昼已${val ? '启用' : '关闭'}`)
  } catch (e: any) {
    ElMessage.error(errMsg(e, '切换失败'))
  } finally {
    toggling.value = false
  }
}

async function savePoint() {
  if (!pointValid.value) return
  try {
    await botApi.saveSleepPoint(props.botId, { x: point.x, y: point.y, z: point.z })
    if (status.value) status.value.sleep_point = { x: point.x, y: point.y, z: point.z }
    ElMessage.success('睡觉点已保存')
  } catch (e: any) {
    ElMessage.error(errMsg(e, '保存失败'))
  }
}

async function clearPoint() {
  try {
    await botApi.clearSleepPoint(props.botId)
    point.x = 0; point.y = 0; point.z = 0
    if (status.value) status.value.sleep_point = null
    ElMessage.success('睡觉点已清除')
  } catch (e: any) {
    ElMessage.error(errMsg(e, '清除失败'))
  }
}

async function sleepNow() {
  if (sleepingNow.value) return
  sleepingNow.value = true
  try {
    const resp = await botApi.sleepNow(props.botId)
    const r = resp.data?.result || {}
    ElMessage[r.success ? 'success' : 'warning'](`结果：${r.reason || (r.success ? '已入睡' : '失败')}`)
    await load()
  } catch (e: any) {
    ElMessage.error(errMsg(e, '睡觉失败'))
  } finally {
    sleepingNow.value = false
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 5000)
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
watch(() => props.botId, () => { load() })
</script>

<style scoped>
.feature-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.feature-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}
.feature-title {
  font-family: var(--font-display, inherit);
  font-weight: 600;
  font-size: 14px;
}
.feature-badge {
  font-size: 11px;
  color: var(--text-muted, #83807a);
}
.feature-card {
  border: 1px solid var(--border-color, rgba(217, 119, 87, 0.25));
  border-radius: 10px;
  padding: 12px;
  background: var(--bg-card, #f5f3ec);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.card-title {
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.state-tag { margin-left: 0; }
.global-tag { opacity: 0.85; }
.card-desc {
  font-size: 11px;
  color: var(--text-muted, #83807a);
  line-height: 1.5;
  margin-bottom: 10px;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}
.status-item {
  border: 1px solid var(--border-color, rgba(217, 119, 87, 0.18));
  border-radius: 8px;
  padding: 6px 8px;
  background: var(--bg-input, rgba(0, 0, 0, 0.02));
}
.status-label {
  display: block;
  font-size: 10px;
  color: var(--text-muted, #83807a);
  margin-bottom: 2px;
}
.status-value {
  font-size: 13px;
  font-weight: 600;
}
.status-value.sleeping { color: var(--color-accent, #d97757); }
.status-value.busy { color: var(--color-warn, #b45309); }
.status-sub {
  font-size: 10px;
  color: var(--text-muted, #83807a);
  font-weight: 400;
}
.last-result {
  font-size: 11px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--bg-input, rgba(0, 0, 0, 0.02));
  margin-bottom: 8px;
}
.result-label { color: var(--text-muted, #83807a); }
.result-reason.ok { color: #2f9e44; }
.result-reason.fail { color: #c92a2a; }
.result-time { color: var(--text-disabled, #b0aca4); margin-left: 6px; }
.warn-line {
  font-size: 11px;
  color: #b45309;
  background: rgba(180, 83, 9, 0.08);
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 8px;
}
.point-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.point-label {
  font-size: 11px;
  color: var(--text-muted, #83807a);
  margin-right: 2px;
}
.point-input {
  width: 92px;
}
.point-input :deep(.el-input__inner) {
  padding: 0 6px;
  text-align: center;
}
.pixel-btn.mini {
  padding: 4px 10px;
  font-size: 11px;
}
.point-hint {
  font-size: 11px;
  color: var(--text-muted, #83807a);
  margin-top: 6px;
  line-height: 1.4;
}
.card-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.empty-text {
  padding: 16px 0;
  text-align: center;
}
</style>