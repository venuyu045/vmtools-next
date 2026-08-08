<template>
  <el-popover placement="top" :width="280" trigger="hover" :show-after="300">
    <template #reference>
      <el-tag size="default" effect="plain" class="player-tag">
        <span class="player-name">{{ player.name }}</span>
        <span class="world-badge" :class="'world-' + player.world">{{ worldLabel(player.world) }}</span>
      </el-tag>
    </template>
    <div class="player-popover">
      <div class="pop-section" v-if="player.residence">
        <span class="pop-label">所在领地</span>
        <span class="pop-value">{{ player.residence.name }}</span>
        <span class="pop-sub">所有者: {{ player.residence.owner }}</span>
      </div>
      <div class="pop-section" v-else>
        <span class="pop-label">所在领地</span>
        <span class="pop-none">无主之地</span>
      </div>
      <div class="pop-divider"></div>
      <div class="pop-section" v-if="player.region">
        <span class="pop-label">区域性能</span>
        <div class="pop-stats">
          <div class="pop-stat"><span>TPS</span><span :class="tpsClass(player.region.tps)">{{ player.region.tps ?? '--' }}</span></div>
          <div class="pop-stat"><span>MSPT</span><span :class="msptClass(player.region.mspt)">{{ player.region.mspt ?? '--' }}ms</span></div>
          <div class="pop-stat"><span>实体</span><span>{{ player.region.entities ?? '--' }}</span></div>
          <div class="pop-stat"><span>区块</span><span>{{ player.region.chunks ?? '--' }}</span></div>
          <div class="pop-stat"><span>区域内玩家</span><span>{{ player.region.players_in_region ?? '--' }}</span></div>
        </div>
      </div>
      <div class="pop-divider" v-if="player.position"></div>
      <div class="pop-section" v-if="player.position">
        <span class="pop-label">坐标</span>
        <span class="pop-sub">{{ player.position.x.toFixed(0) }}, {{ player.position.y.toFixed(0) }}, {{ player.position.z.toFixed(0) }}</span>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import type { OnlinePlayer } from '@/stores/onlinePlayers'

defineProps<{
  player: OnlinePlayer
}>()

const WORLD_LABELS: Record<string, string> = {
  world: '主世界',
  world_nether: '地狱',
  world_the_end: '末地',
}

function worldLabel(world: string): string {
  return WORLD_LABELS[world] || world
}

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
.player-tag {
  background: rgba(64, 158, 255, 0.12);
  border-color: rgba(64, 158, 255, 0.35);
  color: #409eff;
}
.player-name { font-weight: 600; }
.world-badge {
  font-size: 10px;
  line-height: 1;
  padding: 2px 5px;
  margin-left: 6px;
  border-radius: 0;
}
.world-world { background: rgba(0, 200, 83, 0.15); color: #00c853; border: 1px solid rgba(0, 200, 83, 0.35); }
.world-world_nether { background: rgba(255, 152, 0, 0.15); color: #ff9800; border: 1px solid rgba(255, 152, 0, 0.35); }
.world-world_the_end { background: rgba(156, 39, 176, 0.18); color: #ce93d8; border: 1px solid rgba(156, 39, 176, 0.4); }

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
