<template>
  <div class="player-list-page">
    <h2 class="pixel page-title">玩家列表</h2>
    <p class="page-subtitle mono">通过 BlueMap API 实时查看当前在线玩家</p>

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

      <div v-else class="world-groups">
        <div v-for="(list, world) in playerStore.byWorld" :key="world" class="world-group">
          <div class="world-label">
            {{ playerStore.getWorldLabel(world as string) }}
            <span class="world-count">{{ list.length }}</span>
          </div>
          <div class="player-tags">
            <el-popover
              v-for="p in list"
              :key="p.uuid"
              placement="top"
              :width="280"
              trigger="hover"
              :show-after="300"
            >
              <template #reference>
                <el-tag size="default" effect="plain">
                  {{ p.name }}
                </el-tag>
              </template>
              <div class="player-popover">
                <div class="pop-section" v-if="p.residence">
                  <span class="pop-label">🏠 所在领地</span>
                  <span class="pop-value">{{ p.residence.name }}</span>
                  <span class="pop-sub">所有者: {{ p.residence.owner }}</span>
                </div>
                <div class="pop-section" v-else>
                  <span class="pop-label">🏠 所在领地</span>
                  <span class="pop-none">无主之地</span>
                </div>
                <div class="pop-divider"></div>
                <div class="pop-section" v-if="p.region">
                  <span class="pop-label">📊 区域性能</span>
                  <div class="pop-stats">
                    <div class="pop-stat"><span>TPS</span><span :class="tpsClass(p.region.tps)">{{ p.region.tps ?? '--' }}</span></div>
                    <div class="pop-stat"><span>MSPT</span><span :class="msptClass(p.region.mspt)">{{ p.region.mspt ?? '--' }}ms</span></div>
                    <div class="pop-stat"><span>实体</span><span>{{ p.region.entities ?? '--' }}</span></div>
                    <div class="pop-stat"><span>区块</span><span>{{ p.region.chunks ?? '--' }}</span></div>
                    <div class="pop-stat"><span>区域内玩家</span><span>{{ p.region.players_in_region ?? '--' }}</span></div>
                  </div>
                </div>
                <div class="pop-divider" v-if="p.position"></div>
                <div class="pop-section" v-if="p.position">
                  <span class="pop-label">📍 坐标</span>
                  <span class="pop-sub">{{ p.position.x.toFixed(0) }}, {{ p.position.y.toFixed(0) }}, {{ p.position.z.toFixed(0) }}</span>
                </div>
              </div>
            </el-popover>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'

const playerStore = useOnlinePlayersStore()

function tpsClass(tps: number | null): string {
  if (tps === null) return ''
  if (tps >= 19.5) return 'perf-good'
  if (tps >= 17) return 'perf-warn'
  return 'perf-bad'
}

function msptClass(mspt: number | null): string {
  if (mspt === null) return ''
  if (mspt <= 30) return 'perf-good'
  if (mspt <= 45) return 'perf-warn'
  return 'perf-bad'
}
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
.world-groups { display: flex; flex-direction: column; gap: 10px; }
.world-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.world-count { font-size: 11px; color: var(--text-disabled); }
.player-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.player-tags :deep(.el-tag) {
  background: rgba(64, 158, 255, 0.12);
  border-color: rgba(64, 158, 255, 0.35);
  color: #409eff;
}

.player-popover { font-size: 13px; }
.pop-section { margin-bottom: 8px; }
.pop-label { display: block; font-weight: 600; margin-bottom: 4px; font-size: 12px; color: var(--text-secondary); }
.pop-value { font-size: 14px; font-weight: 600; }
.pop-sub { display: block; color: var(--text-disabled); font-size: 12px; margin-top: 2px; }
.pop-none { color: var(--text-disabled); font-style: italic; }
.pop-divider { height: 1px; background: var(--border-subtle); margin: 8px 0; }
.pop-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 8px; }
.pop-stat { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-secondary); }
.pop-stat span:last-child { font-weight: 600; color: inherit; }
.perf-good { color: #00c853 !important; }
.perf-warn { color: #ff9800 !important; }
.perf-bad { color: #f44336 !important; }
</style>