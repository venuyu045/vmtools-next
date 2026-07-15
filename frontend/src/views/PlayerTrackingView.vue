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

    <el-table :data="config.players" style="margin-top:20px">
      <el-table-column prop="name" label="游戏内名称" />
      <el-table-column prop="qq_openid" label="通知 QQ OpenID">
        <template #default="{ row }">
          <code class="mono" v-if="row.qq_openid">{{ row.qq_openid.slice(0, 16) }}...</code>
          <span v-else class="na">未设置</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row, $index }">
          <el-button size="small" @click="editPlayer($index)">编辑</el-button>
          <el-button size="small" type="danger" @click="removePlayer($index)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-button type="primary" @click="addPlayer()" style="margin-top:16px">+ 添加玩家</el-button>

    <el-dialog v-model="showDialog" :title="editingIndex >= 0 ? '编辑玩家' : '添加玩家'" width="420px">
      <el-form label-width="100px">
        <el-form-item label="游戏内名称">
          <el-input v-model="form.name" placeholder="Venus_Yu002" />
        </el-form-item>
        <el-form-item label="QQ OpenID">
          <el-input v-model="form.qq_openid" placeholder="E3D613A55099F0BEE950577A928EFC37" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmPlayer">确定</el-button>
      </template>
    </el-dialog>

    <div class="help-box" style="margin-top:24px">
      <h4>怎么获取 QQ OpenID？</h4>
      <p>让那个 QQ 用户在群里 <strong>@机器人 发一条消息</strong>，然后在服务器运行：</p>
      <code>/opt/vmtools-next/vmtools-next/backend/.venv/bin/python /opt/vmtools-next/vmtools-next/backend/src/vmtools_next/adapters/qqbot/ws_sniffer.py</code>
      <p>终端会显示 <code>发送者 openid=XXXXXXXX</code>，复制填入即可。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '@/api/client'

interface PlayerEntry {
  name: string
  qq_openid: string
}

interface TrackingConfig {
  enabled: boolean
  sentinel_instance: string
  players: PlayerEntry[]
}

const config = reactive<TrackingConfig>({
  enabled: true,
  sentinel_instance: 'bot-001',
  players: [],
})

const showDialog = ref(false)
const editingIndex = ref(-1)
const form = reactive({ name: '', qq_openid: '' })

onMounted(async () => {
  try {
    const { data } = await client.get('/api/player-tracking')
    config.enabled = data.enabled
    config.sentinel_instance = data.sentinel_instance
    config.players = data.players || []
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
})

async function save() {
  try {
    await client.put('/api/player-tracking', {
      enabled: config.enabled,
      sentinel_instance: config.sentinel_instance,
      players: config.players,
    })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

function addPlayer() {
  editingIndex.value = -1
  form.name = ''
  form.qq_openid = ''
  showDialog.value = true
}

function editPlayer(index: number) {
  editingIndex.value = index
  form.name = config.players[index].name
  form.qq_openid = config.players[index].qq_openid
  showDialog.value = true
}

async function removePlayer(index: number) {
  try {
    await ElMessageBox.confirm('确认删除？', '提示', { type: 'warning' })
  } catch { return }
  config.players.splice(index, 1)
  await save()
}

async function confirmPlayer() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入游戏内名称')
    return
  }
  const entry = { name: form.name.trim(), qq_openid: form.qq_openid.trim() }
  if (editingIndex.value >= 0) {
    config.players[editingIndex.value] = entry
  } else {
    config.players.push(entry)
  }
  showDialog.value = false
  await save()
}
</script>

<style scoped>
.player-tracking-page { max-width: 860px; margin: 0 auto; padding: 24px; }
.subtitle { color: var(--text-secondary); margin-bottom: 16px; }
.settings-bar { background: rgba(255,255,255,0.03); padding: 12px 16px; border-radius: 8px; }
.mono { font-family: monospace; font-size: 12px; }
.na { color: var(--text-disabled); font-style: italic; }
.help-box { background: rgba(255,255,255,0.05); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; }
.help-box p { margin: 8px 0; }
.help-box code { background: #000; padding: 2px 6px; border-radius: 4px; font-size: 12px; display: block; margin: 8px 0; overflow-x: auto; }
</style>
