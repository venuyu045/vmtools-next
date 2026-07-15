<template>
  <div class="player-tracking-page">
    <h2>玩家进出追踪</h2>
    <p class="subtitle">监控指定玩家的登录/离线，通知对应 QQ 用户</p>

    <el-form inline class="settings-bar">
      <el-form-item label="启用">
        <el-switch v-model="config.enabled" @change="save" />
      </el-form-item>
      <el-form-item label="监听实例">
        <el-input v-model="config.sentinel_instance" placeholder="bot-001" style="width:120px" />
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
.player-tracking-page { max-width: 860px; margin: 0 auto; padding: 24px; }
.subtitle { color: var(--text-secondary); margin-bottom: 16px; }
.settings-bar { background: rgba(255,255,255,0.03); padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; }
.owner-card { background: rgba(255,255,255,0.04); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.owner-header { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.owner-name { font-size: 16px; font-weight: 600; }
.owner-id { font-size: 11px; color: var(--text-disabled); background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; }
.track-list { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.na { color: var(--text-disabled); font-style: italic; font-size: 13px; }
.help-box { background: rgba(255,255,255,0.05); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; margin-top: 24px; }
.help-box p { margin: 8px 0; }
.help-box code { background: #000; padding: 2px 6px; border-radius: 4px; font-size: 12px; display: block; margin: 8px 0; overflow-x: auto; }
</style>
