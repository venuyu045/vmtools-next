<template>
  <el-card class="panel bot-inventory-panel" header="Bot 背包（实时）">
    <div v-if="!bots.length" class="inv-empty">暂无运行中的 bot（任务启动后显示每个 bot 的背包物品）</div>
    <div v-for="bot in bots" :key="bot.bot_id" class="inv-bot">
      <div class="inv-head">
        <span class="inv-bot-name">{{ bot.bot_name || bot.bot_id }}</span>
        <span class="inv-total">共 {{ bot.total_items }} 件 / {{ bot.items.length }} 种</span>
      </div>

      <!-- 2026-08-18 状态栏：实时服务器时间 / 昼夜 / 强制睡觉按钮 -->
      <div class="inv-sleep-bar">
        <span class="sleep-time" :class="sleepPhaseClass(sleepMap[bot.bot_id])">
          <el-icon v-if="sleepMap[bot.bot_id]?.time_status?.is_sleeping"><Moon /></el-icon>
          <el-icon v-else-if="sleepMap[bot.bot_id]?.time_status?.is_day !== false"><Sunny /></el-icon>
          <el-icon v-else><Moon /></el-icon>
          <template v-if="sleepMap[bot.bot_id]?.time_status?.time_of_day != null">
            {{ fmtTime(sleepMap[bot.bot_id]!.time_status!.time_of_day!) }}
            · {{ sleepPhaseLabel(sleepMap[bot.bot_id]!.time_status!.time_of_day!) }}
            <span v-if="sleepMap[bot.bot_id]?.time_status?.is_sleeping" class="sleep-state">（睡觉中）</span>
          </template>
          <template v-else>时间获取中…</template>
        </span>
        <el-button
          size="small"
          type="warning"
          :disabled="sleepingNow === bot.bot_id"
          :loading="sleepingNow === bot.bot_id"
          @click="handleForceSleep(bot.bot_id)"
        >{{ sleepingNow === bot.bot_id ? '睡觉中…' : '睡觉' }}</el-button>
      </div>

      <div v-if="bot.items.length" class="inv-grid">
        <div v-for="(it, i) in bot.items" :key="i" class="inv-item" :title="zhItemName(it.name)">
          <ItemIcon :item-id="it.name" :name="zhItemName(it.name)" :size="24" class="inv-icon" />
          <span class="inv-name" :class="{ 'inv-low': it.count < 64 }">{{ zhItemName(it.name) }}</span>
          <span class="inv-count" :class="{ 'inv-low': it.count < 64 }">×{{ it.count }}</span>
        </div>
      </div>
      <div v-else class="inv-bot-empty">（背包为空或快照失败）</div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Moon, Sunny } from '@element-plus/icons-vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { mapArtApi } from '@/api/mapArt'
import { zhItemName } from '@/utils/itemZh'

/**
 * Bot 背包面板（2026-08-14）：实时终端下方，展示任务正在工作的每个 bot
 * 的背包物品清单（名称+数量，<64 标红提示不足）。每 3s 轮询 REST 接口。
 * 2026-08-18：新增每 bot 状态栏——实时服务器时间（timeOfDay→时刻）+ 昼夜判断
 * + 睡觉按钮（强制该 bot 前往睡觉点睡觉），轮询 /mcc-bots/{id}/sleep/status。
 */
const props = defineProps<{ taskId: string }>()

const bots = ref<any[]>([])
const sleepMap = reactive<Record<string, any>>({})
const sleepingNow = ref('')
let pollTimer: number | undefined

async function poll() {
  if (!props.taskId) return
  try {
    const { data } = await mapArtApi.getBotsInventory(props.taskId)
    bots.value = data.bots || []
    // 每个 bot 拉一次实时时间状态
    for (const b of bots.value) {
      pollSleepStatus(b.bot_id)
    }
  } catch {
    /* 静默 */
  }
}

async function pollSleepStatus(botId: string) {
  try {
    const { data } = await mapArtApi.getBotSleepStatus(botId)
    sleepMap[botId] = data || {}
  } catch {
    /* bot 离线/未连：忽略 */
  }
}

/** timeOfDay(0~24000，0=06:00) → "HH:MM"（服务器时间，6:00 为日出） */
function fmtTime(tod: number): string {
  const totalMin = Math.floor((tod / 1000) * 60)
  const h = (6 + Math.floor(totalMin / 60)) % 24
  const m = totalMin % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** 昼夜判断：12542~23458 原版可睡窗口=夜晚；其余=白天 */
function sleepPhaseLabel(tod: number): string {
  if (tod >= 12542 && tod <= 23458) return '夜晚'
  if (tod >= 23459) return '凌晨'
  return '白天'
}

function sleepPhaseClass(st: any): string {
  const tod = st?.time_status?.time_of_day
  if (st?.time_status?.is_sleeping) return 'phase-night'
  if (tod == null) return ''
  return tod >= 12542 && tod <= 23458 ? 'phase-night' : 'phase-day'
}

async function handleForceSleep(botId: string) {
  sleepingNow.value = botId
  try {
    const { data } = await mapArtApi.forceBotSleep(props.taskId, botId)
    if (data?.success) {
      ElMessage.success(`${botId} 已前往睡觉点睡觉`)
    } else {
      ElMessage.warning(`${botId} 睡觉未执行：${data?.reason || '未知原因'}`)
    }
  } catch (e: any) {
    ElMessage.error(`睡觉失败：${e?.response?.data?.detail || e.message || '网络错误'}`)
  } finally {
    sleepingNow.value = ''
    pollSleepStatus(botId)
  }
}

onMounted(() => {
  poll()
  pollTimer = window.setInterval(poll, 3000)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.bot-inventory-panel { flex-shrink: 0; }
.inv-empty, .inv-bot-empty {
  color: var(--text-muted);
  padding: 10px 0;
  text-align: center;
  font-size: 12px;
}
.inv-bot {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.inv-bot:last-child { margin-bottom: 0; }
.inv-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.inv-bot-name {
  font-size: 13px;
  font-weight: 600;
  color: #7cb8ff;
}
.inv-total { font-size: 11px; color: var(--text-muted); }
.inv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.inv-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--terminal-bg, #16161d);
  border-radius: 5px;
  padding: 4px 6px;
}
.inv-icon { flex-shrink: 0; }
.inv-name {
  flex: 1;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #d6d6d6;
}
.inv-count { font-size: 11px; color: #888; flex-shrink: 0; }
.inv-low { color: #ff6b6b; }
/* 2026-08-18 状态栏 */
.inv-sleep-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: var(--terminal-bg, #16161d);
  border-radius: 5px;
  padding: 4px 8px;
  margin-bottom: 6px;
}
.sleep-time {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
}
.phase-day { color: #ffd666; }
.phase-night { color: #7cb8ff; }
.sleep-state { color: #7cf7b6; font-weight: 400; }
</style>
