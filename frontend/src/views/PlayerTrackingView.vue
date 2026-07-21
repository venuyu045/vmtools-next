<template>
  <div class="player-tracking-page">
    <h2>玩家进出追踪</h2>
    <p class="subtitle">通过 BlueMap API 实时监控在线玩家，追踪上下线并通知 QQ</p>

    <!-- BlueMap 在线玩家面板 -->
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
            <el-tag
              v-for="p in list"
              :key="p.uuid"
              size="default"
              :type="isTracked(p.name) ? 'success' : 'info'"
              effect="plain"
            >
              {{ p.name }}
            </el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 最近上下线事件 -->
    <div class="events-panel" v-if="playerStore.events.length > 0">
      <h4>最近事件</h4>
      <div class="event-list">
        <div
          v-for="(ev, i) in playerStore.events.slice(0, 20)"
          :key="i"
          class="event-item"
          :class="ev.event"
        >
          <span class="event-time">{{ new Date(ev.time).toLocaleTimeString() }}</span>
          <span class="event-icon">{{ ev.event === 'join' ? '' : '🚪' }}</span>
          <span class="event-name">{{ ev.name }}</span>
          <span class="event-action">{{ ev.event === 'join' ? '上线了' : '离线了' }}</span>
          <span class="event-world" v-if="ev.world">
            ({{ playerStore.getWorldLabel(ev.world) }})
          </span>
        </div>
      </div>
    </div>

    <!-- 追踪配置 -->
    <el-form inline class="settings-bar">
      <el-form-item label="启用通知">
        <el-switch v-model="config.enabled" @change="save" />
      </el-form-item>
      <el-form-item label="监听实例">
        <el-input
          v-model="config.sentinel_instance"
          placeholder="bot-001（BlueMap启用时无需）"
          style="width:180px"
          disabled
        />
        <span class="hint">已由 BlueMap API 接管</span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存设置</el-button>
      </el-form-item>
    </el-form>

    <div v-for="(owner, oi) in config.owners" :key="oi" class="owner-card">
      <div class="owner-header">
        <span class="owner-name">{{ owner.name }}</span>
        <code class="owner-id">{{ owner.qq_openid.slice(0, 20) }}...</code>
      </div>
      <div class="track-list">
        <el-tag
          v-for="(pname, pi) in owner.track_players"
          :key="pi"
          closable
          @close="removePlayer(oi, pi)"
          size="large"
        >
          {{ pname }}
        </el-tag>
        <el-button size="small" type="primary" plain @click="addPlayer(oi)">+ 添加</el-button>
        <span v-if="!owner.track_players.length" class="na">暂未追踪任何玩家</span>
      </div>
    </div>

    <el-dialog v-model="showDialog" title="添加追踪玩家" width="360px">
      <el-form label-width="80px">
        <el-form-item label="玩家名">
          <el-input v-model="form.name" placeholder="游戏内名称" @keyup.enter="confirmPlayer" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmPlayer">添加</el-button>
      </template>
    </el-dialog>

    <div class="help-box">
      <h4>怎么获取 QQ OpenID？</h4>
      <p>让那个 QQ 用户在群里 <strong>@机器人 发一条消息</strong>，在服务器运行：</p>
      <code>/opt/vmtools-next/vmtools-next/backend/.venv/bin/python /opt/vmtools-next/vmtools-next/backend/src/vmtools_next/adapters/qqbot/ws_sniffer.py</code>
      <p>终端显示 <code>发送者 openid=XXXXXXXX</code>，填入上方对应行即可。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import client from '@/api/client'
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'

interface OwnerEntry {
  name: string
  qq_openid: string
  track_players: string[]
}

interface TrackingConfig {
  enabled: boolean
  sentinel_instance: string
  owners: OwnerEntry[]
}

const playerStore = useOnlinePlayersStore()

const config = reactive<TrackingConfig>({
  enabled: true,
  sentinel_instance: 'bot-001',
  owners: [],
})

const showDialog = ref(false)
const editingOwnerIndex = ref(0)
const form = reactive({ name: '' })

const trackedNames = ref<Set<string>>(new Set())

onMounted(async () => {
  try {
    const { data } = await client.get('/player-tracking')
    config.enabled = data.enabled
    config.sentinel_instance = data.sentinel_instance
    config.owners = data.owners || []
    updateTrackedSet()
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
})

function updateTrackedSet() {
  const names = new Set<string>()
  for (const owner of config.owners) {
    for (const p of owner.track_players) {
      names.add(p)
    }
  }
  trackedNames.value = names
}

function isTracked(name: string): boolean {
  for (const t of trackedNames.value) {
    if (name.includes(t) || t.includes(name)) return true
  }
  return false
}

async function save() {
  try {
    await client.put('/player-tracking', {
      enabled: config.enabled,
      sentinel_instance: config.sentinel_instance,
      owners: config.owners,
    })
    updateTrackedSet()
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

function addPlayer(ownerIndex: number) {
  editingOwnerIndex.value = ownerIndex
  form.name = ''
  showDialog.value = true
}

function removePlayer(ownerIndex: number, playerIndex: number) {
  config.owners[ownerIndex].track_players.splice(playerIndex, 1)
  save()
}

async function confirmPlayer() {
  const name = form.name.trim()
  if (!name) { ElMessage.warning('请输入玩家名'); return }
  config.owners[editingOwnerIndex.value].track_players.push(name)
  showDialog.value = false
  await save()
}
</script>

<style scoped>
.player-tracking-page { max-width: 860px; margin: 0 auto; padding: 24px; }
.subtitle { color: var(--text-secondary); margin-bottom: 16px; }

/* 在线面板 */
.online-panel {
  background: rgba(0, 200, 83, 0.06);
  border: 1px solid rgba(0, 200, 83, 0.25);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 20px;
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
.world-group { }
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

/* 事件面板 */
.events-panel {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 20px;
}
.events-panel h4 { margin: 0 0 8px 0; font-size: 14px; color: var(--text-secondary); }
.event-list { max-height: 200px; overflow-y: auto; }
.event-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  font-size: 13px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.event-item.join { }
.event-item.leave { opacity: 0.7; }
.event-time { color: var(--text-disabled); font-size: 11px; min-width: 70px; }
.event-icon { font-size: 14px; }
.event-name { font-weight: 600; }
.event-action { color: var(--text-secondary); }
.event-world { color: var(--text-disabled); font-size: 11px; }

.settings-bar { background: rgba(255,255,255,0.03); padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; }
.settings-bar .hint { font-size: 11px; color: var(--text-disabled); margin-left: 8px; }
.owner-card { background: rgba(255,255,255,0.04); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.owner-header { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.owner-name { font-size: 16px; font-weight: 600; }
.owner-id { font-size: 11px; color: var(--text-disabled); background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; }
.track-list { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.track-list :deep(.el-tag) {
  background: rgba(0, 200, 83, 0.15);
  border: 1px solid var(--green-primary, #00c853);
  color: var(--green-primary, #00c853);
}
.track-list :deep(.el-tag .el-tag__close) { color: var(--green-primary, #00c853); }
.track-list :deep(.el-tag .el-tag__close:hover) { background: rgba(0, 200, 83, 0.3); }
.na { color: var(--text-disabled); font-style: italic; font-size: 13px; }
.help-box { background: rgba(255,255,255,0.05); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; margin-top: 24px; }
.help-box p { margin: 8px 0; }
.help-box code { background: #000; padding: 2px 6px; border-radius: 4px; font-size: 12px; display: block; margin: 8px 0; overflow-x: auto; }
</style>
