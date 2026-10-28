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
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import client from '@/api/client'

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
.page-title { color: var(--text-primary); font-family: var(--font-display); font-size: 24px; font-weight: 400; letter-spacing: -0.6px; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 13px; margin-bottom: 16px; }

.settings-bar { background: var(--bg-hover); padding: 12px 16px; border-radius: var(--radius-md); margin-bottom: 16px; }
.owner-card { background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 16px; margin-bottom: 12px; }
.owner-header { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.owner-name { font-size: 16px; font-weight: 600; }
/* 深色下 --text-disabled(#6A675F) 落在 --bg-hover 上仅约 2.6:1，
   11px 小字几乎不可读；辅助信息提到 --text-muted（深色下约 4.5:1）。 */
.owner-id { font-size: 11px; color: var(--text-muted); background: var(--bg-hover); padding: 2px 6px; border-radius: 4px; }
.track-list { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.track-list :deep(.el-tag) {
  background: var(--success-bg);
  border: 1px solid var(--success);
  color: var(--success);
}
.track-list :deep(.el-tag .el-tag__close) { color: var(--success); }
.track-list :deep(.el-tag .el-tag__close:hover) { background: var(--success-bg); }
.na { color: var(--text-muted); font-style: italic; font-size: 13px; }

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .player-alerts-page { padding: 16px 12px; }
  .settings-bar { flex-direction: column; align-items: stretch; gap: 8px; }
  .owner-header { flex-wrap: wrap; gap: 8px; }
  .owner-id { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
</style>