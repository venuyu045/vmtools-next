<template>
  <div class="player-list-page">
    <h2 class="pixel page-title">玩家列表</h2>
    <p class="page-subtitle mono">通过 BlueMap API 实时查看当前在线玩家（活跃/挂机按坐标变动判定）</p>

    <div class="online-panel">
      <div class="panel-header">
        <h3>
          当前在线
          <span class="count-badge">{{ playerStore.count }}</span>
        </h3>
        <span class="update-time" v-if="playerStore.lastUpdate">
          更新于 {{ new Date(playerStore.lastUpdate).toLocaleTimeString() }}
        </span>
      </div>

      <div v-if="playerStore.count === 0" class="empty-hint">暂无在线玩家</div>

      <div v-else class="player-groups">
        <!-- 活跃玩家（真人，坐标在变动） -->
        <div class="group-block" v-if="playerStore.humanActive.length">
          <div class="group-label">
            <span class="status-dot dot-active"></span>
            活跃玩家
            <span class="group-count">{{ playerStore.humanActive.length }}</span>
          </div>
          <div class="player-tags">
            <PlayerTag v-for="p in playerStore.humanActive" :key="p.uuid" :player="p" />
          </div>
        </div>

        <!-- 挂机玩家（真人，长时间无移动） -->
        <div class="group-block" v-if="playerStore.humanAfk.length">
          <div class="group-label">
            <span class="status-dot dot-afk"></span>
            挂机玩家
            <span class="group-count">{{ playerStore.humanAfk.length }}</span>
          </div>
          <div class="player-tags">
            <PlayerTag v-for="p in playerStore.humanAfk" :key="p.uuid" :player="p" />
          </div>
        </div>

        <!-- Bot（按归属玩家分组，不标活跃/挂机） -->
        <div class="group-block" v-if="playerStore.botTotal">
          <div class="group-label">
            <span class="status-dot dot-bot"></span>
            Bot
            <span class="group-count">{{ playerStore.botTotal }}</span>
          </div>
          <div v-for="g in playerStore.botGroups" :key="g.owner" class="bot-subgroup">
            <div class="bot-owner-label">
              {{ g.label }}
              <span class="group-count">{{ g.players.length }}</span>
            </div>
            <div class="player-tags">
              <PlayerTag v-for="p in g.players" :key="p.uuid" :player="p" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 上下线事件（常驻） -->
    <div class="events-panel">
      <div class="events-header">
        <h4>上下线事件</h4>
        <span class="events-count">共 {{ playerStore.events.length }} 条</span>
      </div>
      <div v-if="playerStore.events.length === 0" class="empty-hint">暂无上下线事件</div>
      <div v-else class="event-list">
        <div
          v-for="(ev, i) in playerStore.events.slice(0, 200)"
          :key="i"
          class="event-item"
          :class="ev.event"
        >
          <span class="event-time">{{ new Date(ev.time).toLocaleString() }}</span>
          <span class="event-dot" :class="ev.event === 'join' ? 'dot-active' : 'dot-leave'"></span>
          <span class="event-name">{{ ev.name }}</span>
          <span class="event-action">{{ ev.event === 'join' ? '上线了' : '离线了' }}</span>
          <span class="event-world" v-if="ev.world">
            ({{ playerStore.getWorldLabel(ev.world) }})
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'
import PlayerTag from '@/components/PlayerTag.vue'

const playerStore = useOnlinePlayersStore()
</script>

<style scoped>
.player-list-page { max-width: 1080px; margin: 0 auto; padding: 24px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 13px; margin-bottom: 16px; }

.online-panel {
  background: rgba(0, 200, 83, 0.06);
  border: 1px solid rgba(0, 200, 83, 0.25);
  border-radius: 8px;
  padding: 16px;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.panel-header h3 { margin: 0; font-size: 16px; display: flex; align-items: center; gap: 8px; }
.count-badge {
  background: #00c853;
  color: #fff;
  font-size: 13px;
  padding: 2px 10px;
  border-radius: 12px;
}
.update-time { font-size: 12px; color: var(--text-disabled); }
.empty-hint { color: var(--text-disabled); font-style: italic; font-size: 13px; }

/* 分组 */
.player-groups { display: flex; flex-direction: column; gap: 14px; }
.group-block { display: flex; flex-direction: column; gap: 6px; }
.group-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.group-count { font-size: 11px; color: var(--text-disabled); }
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot-active { background: #00c853; }
.dot-afk { background: #ff9800; }
.dot-bot { background: #409eff; }
.dot-leave { background: var(--text-muted); }

.bot-subgroup {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-left: 14px;
  border-left: 1px solid rgba(64, 158, 255, 0.25);
}
.bot-owner-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.player-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* 上下线事件（常驻） */
.events-panel {
  margin-top: 20px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 16px;
}
.events-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.events-header h4 { margin: 0; font-size: 14px; color: var(--text-secondary); }
.events-count { font-size: 12px; color: var(--text-disabled); }
.event-list { max-height: 480px; overflow-y: auto; }
.event-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 0;
  font-size: 13px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.event-item.leave { opacity: 0.7; }
.event-time { color: var(--text-disabled); font-size: 11px; min-width: 150px; }
.event-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.event-name { font-weight: 600; }
.event-action { color: var(--text-secondary); }
.event-world { color: var(--text-disabled); font-size: 11px; }
</style>