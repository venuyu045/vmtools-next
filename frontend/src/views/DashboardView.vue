<template>
  <div class="dashboard">
    <!-- Stats Row（仅用户权限组可见内容） -->
    <div class="stats-row">
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(0,255,0,0.3)">
          <span class="stat-value" style="color: var(--green-primary)">{{ statValue(botStore.loading, botStore.bots.length > 0, botStore.onlineCount) }}</span>
        </div>
        <div>
          <div class="stat-label">在线 Bot</div>
          <div class="stat-sub">MCC + MF</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(24,144,255,0.3)">
          <span class="stat-value" style="color: #1890ff">{{ localPlayerCount }}</span>
        </div>
        <div>
          <div class="stat-label">在线玩家</div>
          <div class="stat-sub">实时</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(255,255,0,0.3)">
          <span class="stat-value" style="color: #ffff00">{{ statValue(warehouseStore.loading, warehouseStore.warehouses.length > 0, warehouseStore.warehouses.length) }}</span>
        </div>
        <div>
          <div class="stat-label">仓库数量</div>
          <div class="stat-sub">{{ fmtBigNum(totalItems) }} 物品</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(255,152,0,0.3)">
          <span class="stat-value" style="color: #ff9800">{{ playerStore.events.length }}</span>
        </div>
        <div>
          <div class="stat-label">上下线事件</div>
          <div class="stat-sub">最近记录</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="stat-indicator" style="border-color: rgba(171,71,188,0.3)">
          <span class="stat-value" style="color: #ab47bc">{{ playerStore.residences.length }}</span>
        </div>
        <div>
          <div class="stat-label">妙妙领地</div>
          <div class="stat-sub">{{ playerStore.regions.length }} 区域 · {{ playerStore.markers.length }} 标记</div>
        </div>
      </div>
    </div>

    <!-- Content Row -->
    <div class="content-row">
      <!-- Left: 在线玩家 + 在线 Bot -->
      <div class="left-col">
        <div class="pixel-card online-players">
          <div class="section-header">
            <h3 class="pixel section-title">当前在线玩家</h3>
            <router-link to="/player-tracking" class="view-all mono">查看全部 ></router-link>
          </div>
          <div v-if="playerStore.count === 0" class="empty-text mono">-- 暂无在线玩家 --</div>
          <div v-else class="world-groups">
            <div v-for="(list, world) in playerStore.byWorld" :key="world" class="world-group">
              <div class="world-label">
                {{ playerStore.getWorldLabel(world as string) }}
                <span class="world-count">{{ list.length }}</span>
              </div>
              <div class="player-tags">
                <el-tag v-for="p in list" :key="p.uuid" size="small" effect="plain">{{ p.name }}</el-tag>
              </div>
            </div>
          </div>
        </div>

        <div class="pixel-card bots-panel">
          <div class="section-header">
            <h3 class="pixel section-title">在线 Bot</h3>
            <router-link to="/mcc-status" class="view-all mono">MCC 状态 ></router-link>
            <router-link to="/mf-status" class="view-all mono">MF 状态 ></router-link>
          </div>
          <div v-if="botStore.onlineBots.length === 0" class="empty-text mono">-- 暂无在线 Bot --</div>
          <div v-else class="bot-list">
            <div v-for="bot in botStore.onlineBots.slice(0, 6)" :key="bot.bot_id" class="bot-row">
              <span class="bot-dot"></span>
              <span class="bot-name">{{ bot.name || bot.bot_id }}</span>
              <span class="bot-id mono">{{ bot.bot_id }}</span>
            </div>
            <div v-if="botStore.onlineBots.length > 6" class="more-hint mono">… 还有 {{ botStore.onlineBots.length - 6 }} 个，见状态页</div>
          </div>
        </div>
      </div>

      <!-- Right: 仓库状态 + 上下线事件 -->
      <div class="right-col">
        <div class="pixel-card warehouse-panel">
          <div class="section-header">
            <h3 class="pixel section-title">仓库状态</h3>
            <router-link to="/warehouse-status" class="view-all mono">查看全部 ></router-link>
          </div>
          <div v-if="warehouseStore.warehouses.length === 0" class="empty-text mono">-- 暂无仓库数据 --</div>
          <div v-else class="wh-list">
            <div v-for="w in warehouseStore.warehouses.slice(0, 5)" :key="w.warehouse_id" class="wh-row">
              <span class="wh-name">{{ w.name || w.warehouse_id.slice(0, 8) }}</span>
              <span class="wh-meta mono">{{ fmtBigNum(w.total_items || 0) }} 物品</span>
            </div>
            <div v-if="warehouseStore.warehouses.length > 5" class="more-hint mono">… 还有 {{ warehouseStore.warehouses.length - 5 }} 个仓库</div>
          </div>
        </div>

        <div class="pixel-card events-panel">
          <div class="section-header">
            <h3 class="pixel section-title">最近上下线</h3>
            <router-link to="/player-tracking" class="view-all mono">更多 ></router-link>
          </div>
          <div v-if="playerStore.events.length === 0" class="empty-text mono">-- 暂无上下线事件 --</div>
          <div v-else class="event-list">
            <div
              v-for="(ev, i) in playerStore.events.slice(0, 10)"
              :key="i"
              class="event-item"
              :class="ev.event"
            >
              <span class="event-icon">{{ ev.event === 'join' ? '⬆' : '⬇' }}</span>
              <span class="event-name">{{ ev.name }}</span>
              <span class="event-action">{{ ev.event === 'join' ? '上线' : '离线' }}</span>
              <span class="event-time mono">{{ fmtTime(ev.time) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useBotStore } from '@/stores/bot'
import { useWarehouseStore } from '@/stores/warehouse'
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'
import { fmtBigNum } from '@/utils/format'

const botStore = useBotStore()
const warehouseStore = useWarehouseStore()
const playerStore = useOnlinePlayersStore()

const totalItems = computed(() => warehouseStore.warehouses.reduce((sum, w) => sum + (w.total_items || 0), 0))

// 在线玩家统计：与「当前在线玩家」面板口径一致（排除 foreign 玩家，避免数字与列表不符）
const localPlayerCount = computed(() => playerStore.players.filter(p => !p.foreign).length)

// 统计卡加载态：数据尚未就绪时显示 "--"，避免首次进入闪烁 0
function statValue(loading: boolean, hasData: boolean, value: number | string): string {
  if (loading && !hasData) return '--'
  return String(value)
}

function fmtTime(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  // 跨天事件带日期，避免只看时分无法区分昨天/今天
  const sameDay = d.toDateString() === new Date().toDateString()
  return sameDay ? hm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
}

let interval: ReturnType<typeof setInterval> | undefined

onMounted(async () => {
  try {
    await Promise.all([
      botStore.fetchBots(),
      warehouseStore.fetchWarehouses(),
    ])
  } catch (e) {
    console.error('[Dashboard] 初始数据加载失败:', e)
  }
  // 玩家在线数/领地数由 Socket.IO 推送（online_players_update / residences_update），
  // 此处仅定期刷新 Bot 状态（玩家数据不额外拉取，避免大体积请求）。
  interval = setInterval(() => {
    botStore.fetchBots().catch((e) => {
      console.error('[Dashboard] Bot 状态刷新失败:', e)
    })
  }, 10000)
})

onBeforeUnmount(() => {
  if (interval) clearInterval(interval)
})
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 24px; }

.stats-row { display: flex; gap: 16px; flex-wrap: wrap; }

.stat-item {
  flex: 1 1 150px;
  min-width: 170px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-indicator {
  border: 1px solid;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
}

.stat-value {
  font-size: 22px;
  font-family: var(--font-mono);
  font-weight: 700;
}

.stat-label { font-size: 14px; color: var(--text-primary); font-weight: 600; }
.stat-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

.content-row { display: flex; gap: 24px; }
.left-col { flex: 1; display: flex; flex-direction: column; gap: 24px; min-width: 0; }
.right-col { width: 360px; flex-shrink: 0; display: flex; flex-direction: column; gap: 24px; }

.section-title { font-size: 14px; color: var(--green-primary); margin-bottom: 16px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 10px; flex-wrap: wrap; }
.section-header .section-title { margin-bottom: 0; }

.view-all { font-size: 13px; color: var(--green-primary); opacity: 0.6; text-decoration: none; }
.view-all:hover { opacity: 1; }

.empty-text { color: var(--text-muted); text-align: center; padding: 20px; font-size: 14px; }

.more-hint { font-size: 12px; color: var(--text-disabled); text-align: center; padding: 8px 0 2px; }

/* 在线玩家 */
.world-groups { display: flex; flex-direction: column; gap: 10px; }
.world-label { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.world-count { font-size: 11px; color: var(--text-disabled); }
.player-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.player-tags :deep(.el-tag) {
  background: rgba(64, 158, 255, 0.12);
  border-color: rgba(64, 158, 255, 0.35);
  color: #409eff;
}

/* 在线 Bot */
.bot-list { display: flex; flex-direction: column; gap: 6px; }
.bot-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border-subtle); }
.bot-row:last-child { border-bottom: none; }
.bot-dot { width: 8px; height: 8px; background: var(--green-primary); flex-shrink: 0; }
.bot-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.bot-id { font-size: 11px; color: var(--text-muted); margin-left: auto; }

/* 仓库状态 */
.wh-list { display: flex; flex-direction: column; gap: 6px; }
.wh-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border-subtle); }
.wh-row:last-child { border-bottom: none; }
.wh-name { font-size: 14px; color: var(--text-primary); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-meta { font-size: 12px; color: var(--text-secondary); margin-left: auto; }

/* 上下线事件 */
.event-list { display: flex; flex-direction: column; }
.event-item { display: flex; align-items: center; gap: 8px; padding: 7px 0; font-size: 13px; border-bottom: 1px solid var(--border-subtle); }
.event-item:last-child { border-bottom: none; }
.event-item.leave { opacity: 0.7; }
.event-icon { font-size: 13px; }
.event-name { font-weight: 600; color: var(--text-primary); }
.event-action { color: var(--text-secondary); }
.event-time { color: var(--text-muted); font-size: 11px; margin-left: auto; }

/* ============ RESPONSIVE ============ */
@media (max-width: 1024px) {
  .content-row { flex-direction: column; }
  .right-col { width: 100%; flex-shrink: 1; }
}

@media (max-width: 768px) {
  .dashboard { gap: 16px; }
  .stats-row { gap: 10px; }
  .stats-row .stat-item { flex: 1 1 calc(50% - 10px); min-width: 140px; padding: 16px; gap: 10px; }
  .content-row { gap: 16px; }
  .left-col, .right-col { gap: 16px; }
}

@media (max-width: 480px) {
  .dashboard { gap: 12px; }
  .stats-row { gap: 8px; }
  .stats-row .stat-item { padding: 12px; gap: 8px; }
  .stat-value { font-size: 16px; }
  .stat-label { font-size: 11px; }
  .stat-sub { font-size: 12px; }
  .pixel-card { padding: 16px; }
  .section-title { font-size: 12px; margin-bottom: 12px; }
  .bot-name { font-size: 13px; }
  .wh-name { font-size: 13px; }
  .event-time { font-size: 10px; }
}
</style>