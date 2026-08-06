<template>
  <div class="player-alerts-page">
    <h2 class="pixel page-title">上下线提醒</h2>
    <p class="page-subtitle mono">配置 QQ 通知 · 追踪指定玩家的上下线并记录事件</p>

    <!-- 追踪配置 -->
    <el-form inline class="settings-bar">
      <el-form-item label="启用通知">
        <el-switch v-model="config.enabled" @change="save" />
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

    <!-- 上下线事件（常驻列表） -->
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
          <span class="event-icon">{{ ev.event === 'join' ? '⬆' : '⬇' }}</span>
          <span class="event-name">{{ ev.name }}</span>
          <span class="event-action">{{ ev.event === 'join' ? '上线了' : '离线了' }}</span>
          <span class="event-world" v-if="ev.world">
            ({{ playerStore.getWorldLabel(ev.world) }})
          </span>
        </div>
      </div>
    </div>

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

onMounted(async () => {
  try {
    const { data } = await client.get('/player-tracking')
    config.enabled = data.enabled
    config.sentinel_instance = data.sentinel_instance
    config.owners = data.owners || []
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
})

async function save() {
  try {
    await client.put('/player-tracking', {
      enabled: config.enabled,
      sentinel_instance: config.sentinel_instance,
      owners: config.owners,
    })
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
.player-alerts-page { max-width: 1080px; margin: 0 auto; padding: 24px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 13px; margin-bottom: 16px; }

.settings-bar { background: rgba(255,255,255,0.03); padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; }
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

/* 上下线事件（常驻列表） */
.events-panel {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 20px;
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
.event-icon { font-size: 14px; }
.event-name { font-weight: 600; }
.event-action { color: var(--text-secondary); }
.event-world { color: var(--text-disabled); font-size: 11px; }
.empty-hint { color: var(--text-disabled); font-style: italic; font-size: 13px; padding: 16px 0; text-align: center; }

.help-box { background: rgba(255,255,255,0.05); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; margin-top: 24px; }
.help-box p { margin: 8px 0; }
.help-box code { background: #000; padding: 2px 6px; border-radius: 4px; font-size: 12px; display: block; margin: 8px 0; overflow-x: auto; }
</style>