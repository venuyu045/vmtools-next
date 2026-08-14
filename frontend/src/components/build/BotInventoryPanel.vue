<template>
  <el-card class="panel bot-inventory-panel" header="Bot 背包（实时）">
    <div v-if="!bots.length" class="inv-empty">暂无运行中的 bot（任务启动后显示每个 bot 的背包物品）</div>
    <div v-for="bot in bots" :key="bot.bot_id" class="inv-bot">
      <div class="inv-head">
        <span class="inv-bot-name">{{ bot.bot_name || bot.bot_id }}</span>
        <span class="inv-total">共 {{ bot.total_items }} 件 / {{ bot.items.length }} 种</span>
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
import { ref, onMounted, onUnmounted } from 'vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { mapArtApi } from '@/api/mapArt'
import { zhItemName } from '@/utils/itemZh'

/**
 * Bot 背包面板（2026-08-14）：实时终端下方，展示任务正在工作的每个 bot
 * 的背包物品清单（名称+数量，<64 标红提示不足）。每 3s 轮询 REST 接口。
 */
const props = defineProps<{ taskId: string }>()

const bots = ref<any[]>([])
let pollTimer: number | undefined

async function poll() {
  if (!props.taskId) return
  try {
    const { data } = await mapArtApi.getBotsInventory(props.taskId)
    bots.value = data.bots || []
  } catch {
    /* 静默：任务未运行/网络失败不影响 */
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
</style>
