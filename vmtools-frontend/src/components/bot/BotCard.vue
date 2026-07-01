<template>
  <div class="bot-card pixel-card">
    <div class="bot-header">
      <span :class="['status-dot', bot.status === 'online' ? 'online' : bot.status === 'offline' ? 'offline' : 'warning']"></span>
      <span class="bot-name pixel">{{ bot.name || bot.bot_id }}</span>
      <span :class="['pixel-badge', bot.status === 'online' ? 'green' : bot.status === 'offline' ? 'red' : 'yellow']">
        <span class="badge-dot"></span>
        {{ bot.status === 'online' ? 'ONLINE' : bot.status === 'offline' ? 'OFFLINE' : 'IDLE' }}
      </span>
    </div>

    <div class="bot-meta mono">
      <div>服: {{ bot.mc_server_host || '未知' }}</div>
      <div>MC {{ bot.mc_username || '-' }}</div>
    </div>

    <div class="bot-bars">
      <div class="bar-row">
        <span class="bar-label">HP</span>
        <div class="pixel-progress">
          <div class="pixel-progress-fill red" :style="{ width: bot.current_health + '%' }"></div>
        </div>
      </div>
      <div class="bar-row">
        <span class="bar-label">FD</span>
        <div class="pixel-progress">
          <div class="pixel-progress-fill yellow" :style="{ width: bot.current_food + '%' }"></div>
        </div>
      </div>
    </div>

    <div class="bot-actions">
      <button
        v-if="bot.status !== 'online'"
        class="pixel-btn outline"
        @click="$emit('connect', bot)"
      >
        连接
      </button>
      <button
        v-else
        class="pixel-btn warning"
        @click="$emit('disconnect', bot)"
      >
        断开
      </button>
      <button class="pixel-btn danger" @click="$emit('delete', bot)">删除</button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ bot: any }>()
defineEmits(['connect', 'disconnect', 'delete'])
</script>

<style scoped>
.bot-card { margin-bottom: 16px; }
.bot-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.bot-name { font-size: 14px; color: var(--text-primary); flex: 1; }
.bot-meta { color: var(--text-secondary); font-size: 14px; line-height: 1.6; margin-bottom: 12px; }
.bot-bars { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.bar-row { display: flex; align-items: center; gap: 8px; }
.bar-label { font-family: var(--font-mono); font-size: 13px; width: 24px; flex-shrink: 0; }
.bar-label:first-child { color: #ff0000; }
.bar-row:last-child .bar-label { color: #ffff00; }
.bot-actions { display: flex; gap: 8px; }
.pixel-btn { padding: 7px 0; flex: 1; font-size: 13px; }
</style>
