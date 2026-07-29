<template>
  <div class="bots-page">
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">Bot 管理</h2>
        <div class="mono page-subtitle">{{ mccStore.runningCount }} 运行中 / {{ mccStore.totalCount }} 实例</div>
      </div>
      <div class="header-actions">
        <button class="pixel-btn outline" :class="{ active: sortMode === 'name' }" @click="sortMode = 'name'">按名称</button>
        <button class="pixel-btn outline" :class="{ active: sortMode === 'running' }" @click="sortMode = 'running'">运行优先</button>
        <button class="pixel-btn warning" :disabled="mccStore.runningCount === 0" @click="stopAll">一键停止</button>
        <button class="pixel-btn danger" @click="forceKillAll">强制终止所有</button>
        <button class="pixel-btn outline" @click="refreshAll">刷新</button>
        <button class="pixel-btn" @click="showCreate = true">+ 新建实例</button>
      </div>
    </div>

    <div v-loading="mccStore.loading" class="instance-grid">
      <div v-if="sortedInstances.length === 0" class="empty-text mono">-- 暂无 Bot 实例，点击右上角新建 --</div>
      <div
        v-for="instance in sortedInstances"
        :key="instance.instance_id"
        class="pixel-card instance-card"
        @click="openInstance(instance, 'terminal')"
      >
        <div class="instance-head">
          <div>
            <div class="instance-name">{{ instance.display_name || instance.slug }}</div>
            <div class="mono instance-slug">{{ instance.slug }}</div>
          </div>
          <span :class="['pixel-badge', instanceBadgeClass(instance.status)]">
            <span class="badge-dot"></span>
            {{ instance.status }}
          </span>
        </div>

        <!-- Bot connection status -->
        <div v-if="getBot(instance)" class="bot-status-row">
          <span :class="['status-dot-mini', botStatusDotClass(getBot(instance)!.status)]"></span>
          <span class="bot-status-label">{{ botStatusLabel(getBot(instance)!.status) }}</span>
          <span class="mono bot-server">{{ serverLabel(instance) }}</span>
        </div>

        <!-- HP / Food bars (only when bot is online) -->
        <div v-if="getBot(instance)?.status === 'online'" class="bot-bars">
          <div class="bar-row">
            <span class="bar-label hp">HP</span>
            <div class="pixel-progress">
              <div class="pixel-progress-fill red" :style="{ width: getBot(instance)!.current_health + '%' }"></div>
            </div>
            <span class="bar-val mono">{{ getBot(instance)!.current_health }}</span>
          </div>
          <div class="bar-row">
            <span class="bar-label fd">FD</span>
            <div class="pixel-progress">
              <div class="pixel-progress-fill yellow" :style="{ width: getBot(instance)!.current_food + '%' }"></div>
            </div>
            <span class="bar-val mono">{{ getBot(instance)!.current_food }}</span>
          </div>
        </div>

        <div class="instance-dir mono" :title="instance.instance_dir">{{ instance.instance_dir }}</div>

        <div class="actions" @click.stop>
          <button class="pixel-btn" :disabled="instance.status === 'running' || isBusy(instance.instance_id)" @click="handleStart(instance)">启动</button>
          <button class="pixel-btn warning" :disabled="instance.status !== 'running' || isBusy(instance.instance_id)" @click="handleStop(instance)">停止</button>

          <!-- Bot connect / disconnect -->
          <button
            v-if="!getBot(instance) || getBot(instance)!.status !== 'online'"
            class="pixel-btn outline"
            @click="handleConnect(instance)"
          >连接</button>
          <button
            v-else
            class="pixel-btn warning"
            @click="handleDisconnect(instance)"
          >断开</button>

          <router-link :to="'/bots/' + instance.instance_id + '/terminal'" class="pixel-btn outline terminal-link" @click.stop>终端</router-link>
          <router-link :to="'/bots/' + instance.instance_id + '/files'" class="pixel-btn outline terminal-link" @click.stop>文件</router-link>
          <button class="pixel-btn danger" :disabled="instance.status === 'running'" @click="handleDelete(instance)">删除</button>
          <label class="reconnect-toggle" :title="instance.auto_reconnect ? '已开启自动重连' : '开启自动重连'">
            <input type="checkbox" :checked="instance.auto_reconnect" @change="toggleReconnect(instance, $event)" />
            <span class="mono toggle-label">自动重连</span>
          </label>
        </div>
      </div>
    </div>

    <!-- Create instance dialog -->
    <el-dialog v-model="showCreate" title="新建 MCC 实例" width="560px">
      <el-form :model="createForm" label-width="110px">
        <el-form-item label="目录名 slug"><el-input v-model="createForm.slug" placeholder="bot-alice" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="createForm.display_name" placeholder="Alice Bot" /></el-form-item>
        <el-form-item label="Bot ID">
          <el-input v-model="createForm.bot_id" placeholder="可选：关联已有 Bot，留空自动生成" />
        </el-form-item>
        <el-form-item label="账号模板">
          <el-select v-model="createForm.account_profile_id" clearable placeholder="可选：从账号模板继承">
            <el-option v-for="profile in mccStore.accountProfiles" :key="profile.profile_id" :label="`${profile.name} · ${profile.username}`" :value="profile.profile_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="MC 用户名"><el-input v-model="createForm.mc_username" placeholder="离线名/账号名" /></el-form-item>
        <el-form-item label="服务器地址"><el-input v-model="createForm.mc_server_host" placeholder="play.example.com" /></el-form-item>
        <el-form-item label="服务器端口"><el-input-number v-model="createForm.mc_server_port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="游戏版本"><el-input v-model="createForm.mc_version" placeholder="1.21.1" /></el-form-item>
        <el-form-item label="程序模式">
          <el-select v-model="createForm.binary_mode">
            <el-option label="符号链接（推荐）" value="symlink" />
            <el-option label="复制程序" value="copy" />
            <el-option label="外部路径" value="external" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- Detail drawer (Terminal / Account / Files) -->
    <el-drawer v-model="detailOpen" size="72%" :title="drawerTitle">
      <div v-if="selectedInstance" class="detail-panel">
        <div class="terminal-meta mono">
          <span>{{ selectedInstance.display_name }}</span>
          <span>PID: {{ selectedInstance.pid || '--' }}</span>
          <span>PORT: {{ selectedInstance.mcp_port }}</span>
          <span>{{ selectedInstance.instance_dir }}</span>
        </div>

        <el-tabs v-model="activeTab" class="mcc-tabs" @tab-change="handleTabChange">
          <el-tab-pane label="Terminal" name="terminal">
            <MccWebTerminal
              v-if="selectedInstance"
              :instance-id="selectedInstance.instance_id"
              :slug="selectedInstance.slug"
              :title="selectedInstance.display_name || selectedInstance.slug"
              height="480px"
              embedded
            />
          </el-tab-pane>

          <el-tab-pane label="Account" name="account">
            <div class="account-toolbar">
              <el-select v-model="selectedProfileId" clearable placeholder="选择账号模板应用到此实例">
                <el-option v-for="profile in mccStore.accountProfiles" :key="profile.profile_id" :label="`${profile.name} · ${profile.username}`" :value="profile.profile_id" />
              </el-select>
              <button class="pixel-btn outline" :disabled="!selectedProfileId" @click="applySelectedProfile">应用模板</button>
              <button class="pixel-btn outline" @click="showProfileCreate = true">新建模板</button>
            </div>
            <el-form :model="accountForm" label-width="130px" class="account-form">
              <el-form-item label="登录方式">
                <el-select v-model="accountForm.auth_type">
                  <el-option label="离线模式" value="offline" />
                  <el-option label="Microsoft 正版" value="microsoft" />
                  <el-option label="Mojang" value="mojang" />
                  <el-option label="Yggdrasil / 皮肤站" value="yggdrasil" />
                  <el-option label="自定义认证" value="custom" />
                </el-select>
              </el-form-item>
              <el-form-item label="用户名/邮箱"><el-input v-model="accountForm.username" /></el-form-item>
              <el-form-item label="密码"><el-input v-model="accountForm.password" type="password" show-password :placeholder="accountForm.password_set ? '已保存；留空则不修改' : '可选'" /></el-form-item>
              <el-form-item label="认证服务器"><el-input v-model="accountForm.auth_server_url" placeholder="https://auth.example.com" /></el-form-item>
              <el-form-item label="API Path"><el-input v-model="accountForm.auth_api_path" placeholder="/api/yggdrasil" /></el-form-item>
              <el-form-item label="Authlib Injector"><el-input v-model="accountForm.authlib_injector_path" placeholder="authlib-injector.jar 路径" /></el-form-item>
              <el-form-item label="MC 服务器"><el-input v-model="accountForm.mc_server_host" placeholder="play.example.com" /></el-form-item>
              <el-form-item label="服务器端口"><el-input-number v-model="accountForm.mc_server_port" :min="1" :max="65535" /></el-form-item>
              <el-form-item label="游戏版本"><el-input v-model="accountForm.mc_version" /></el-form-item>
              <el-form-item label="MCP 端口"><el-input :model-value="accountForm.mcp_port" disabled /></el-form-item>
              <el-form-item>
                <button class="pixel-btn" type="button" @click="saveAccountConfig">保存 MinecraftClient.ini</button>
                <button class="pixel-btn warning" type="button" :disabled="selectedInstance.status !== 'running'" @click="handleRestart(selectedInstance)">保存后重启</button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="Files" name="files">
            <MccFileManagerPanel
              v-if="selectedInstance"
              :instance-id="selectedInstance.instance_id"
              :slug="selectedInstance.slug"
              embedded
            />
          </el-tab-pane>

          <el-tab-pane label="背包" name="inventory">
            <div v-if="selectedInstance" class="inventory-tab">
              <InventoryGrid
                :bot-id="selectedInstance.bot_id || ''"
                :inventory="inventoryData"
                :loading="inventoryLoading"
                @refresh="fetchInventory"
                @action="handleInventoryAction"
                @drop="handleInventoryDrop"
              />
            </div>
            <div v-else class="empty-state">选择 Bot 实例查看背包</div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <!-- Create account profile dialog -->
    <el-dialog v-model="showProfileCreate" title="新建账号模板" width="560px">
      <el-form :model="profileForm" label-width="120px">
        <el-form-item label="模板名"><el-input v-model="profileForm.name" placeholder="Alice 正版账号" /></el-form-item>
        <el-form-item label="登录方式">
          <el-select v-model="profileForm.auth_type">
            <el-option label="离线模式" value="offline" />
            <el-option label="Microsoft 正版" value="microsoft" />
            <el-option label="Mojang" value="mojang" />
            <el-option label="Yggdrasil / 皮肤站" value="yggdrasil" />
            <el-option label="自定义认证" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="用户名/邮箱"><el-input v-model="profileForm.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="profileForm.password" type="password" show-password /></el-form-item>
        <el-form-item label="认证服务器"><el-input v-model="profileForm.auth_server_url" /></el-form-item>
        <el-form-item label="API Path"><el-input v-model="profileForm.auth_api_path" /></el-form-item>
        <el-form-item label="MC 服务器"><el-input v-model="profileForm.mc_server_host" /></el-form-item>
        <el-form-item label="服务器端口"><el-input-number v-model="profileForm.mc_server_port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="游戏版本"><el-input v-model="profileForm.mc_version" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showProfileCreate = false">取消</el-button>
        <el-button type="primary" @click="createProfile">创建模板</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MccWebTerminal from '@/components/MccWebTerminal.vue'
import MccFileManagerPanel from '@/components/MccFileManagerPanel.vue'
import InventoryGrid from '@/components/bot/InventoryGrid.vue'
import { useMccInstanceStore } from '@/stores/mccInstance'
import { useBotStore } from '@/stores/bot'
import { botApi } from '@/api/bot'
import type { MccAccountConfig, MccAuthType, MccInstance } from '@/api/mccInstance'
import { mccInstanceApi } from '@/api/mccInstance'

const mccStore = useMccInstanceStore()
const botStore = useBotStore()

const showCreate = ref(false)
const showProfileCreate = ref(false)
const detailOpen = ref(false)
const activeTab = ref<'terminal' | 'account' | 'files' | 'inventory'>('terminal')

// Inventory state
const inventoryData = ref<any>(null)
const inventoryLoading = ref(false)
const selectedInstance = ref<MccInstance | null>(null)
const selectedProfileId = ref('')
const lastDiff = ref('')
const sortMode = ref<'name' | 'running'>('running')

const sortedInstances = computed(() => {
  const items = [...mccStore.instances]
  if (sortMode.value === 'name') {
    return items.sort((a, b) => (a.display_name || a.slug).localeCompare(b.display_name || b.slug))
  }
  return items.sort((a, b) => {
    if (a.status === 'running' && b.status !== 'running') return -1
    if (a.status !== 'running' && b.status === 'running') return 1
    return (a.display_name || a.slug).localeCompare(b.display_name || b.slug)
  })
})

const createForm = reactive({
  slug: '',
  display_name: '',
  bot_id: '' as string | null,
  account_profile_id: null as string | null,
  binary_mode: 'symlink' as 'symlink' | 'copy' | 'external',
  mc_username: '',
  mc_server_host: '',
  mc_server_port: 25565,
  mc_version: '1.21.1',
})

const accountForm = reactive<MccAccountConfig>({
  auth_type: 'offline',
  username: '',
  password_set: false,
  password: '',
  auth_server_url: '',
  auth_api_path: '',
  authlib_injector_path: '',
  mc_server_host: '',
  mc_server_port: 25565,
  mc_version: '1.21.1',
  mcp_port: 0,
  mcp_auth_token_env: 'MCC_MCP_AUTH_TOKEN',
})

const profileForm = reactive({
  name: '',
  auth_type: 'offline' as MccAuthType,
  username: '',
  password: '',
  auth_server_url: '',
  auth_api_path: '',
  authlib_injector_path: '',
  mc_server_host: '',
  mc_server_port: 25565,
  mc_version: '1.21.1',
})

const drawerTitle = computed(() => selectedInstance.value ? `Bot · ${selectedInstance.value.display_name || selectedInstance.value.slug}` : 'Bot')

// Look up bot by instance's bot_id
function getBot(instance: MccInstance) {
  if (!instance.bot_id) return null
  return botStore.bots.find(b => b.bot_id === instance.bot_id) || null
}

function instanceBadgeClass(status: string): string {
  if (status === 'running') return 'green'
  if (status === 'error' || status === 'crashed') return 'red'
  if (status === 'starting' || status === 'stopping') return 'yellow'
  return 'green muted'
}

function botStatusDotClass(status: string): string {
  const map: Record<string, string> = { online: 'online', connecting: 'warning', error: 'error', offline: 'offline' }
  return map[status] || 'warning'
}

function botStatusLabel(status: string): string {
  const map: Record<string, string> = { online: 'BOT ONLINE', connecting: 'CONNECTING', error: 'ERROR', offline: 'OFFLINE' }
  return map[status] || 'IDLE'
}

function serverLabel(instance: MccInstance): string {
  if (!instance.mc_server_host) return ''
  return `${instance.mc_server_host}:${instance.mc_server_port}`
}

function isBusy(instanceId: string): boolean {
  return !!mccStore.actionLoading[instanceId]
}

async function refreshAll() {
  await Promise.all([mccStore.fetchInstances(), mccStore.fetchProfiles(), botStore.fetchBots()])
}

async function handleCreate() {
  if (!createForm.slug.trim()) {
    ElMessage.warning('请输入 slug')
    return
  }
  const payload: any = { ...createForm }
  if (!payload.bot_id) delete payload.bot_id
  await mccStore.createInstance(payload)
  showCreate.value = false
  Object.assign(createForm, { slug: '', display_name: '', bot_id: '', account_profile_id: null, binary_mode: 'symlink', mc_username: '', mc_server_host: '', mc_server_port: 25565, mc_version: '1.21.1' })
  ElMessage.success('MCC 实例已创建')
}

async function handleStart(instance: MccInstance) {
  try {
    await mccStore.startInstance(instance.instance_id)
    await mccStore.fetchTerminalHistory(instance.instance_id)
    ElMessage.success('启动命令已发送')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '启动失败，请检查 MCC 程序路径')
  }
}

async function handleStop(instance: MccInstance) {
  await mccStore.stopInstance(instance.instance_id)
  ElMessage.success('停止命令已发送')
}

async function stopAll() {
  try {
    await ElMessageBox.confirm(`确认停止所有 ${mccStore.runningCount} 个运行中的实例？`, '一键停止', { type: 'warning' })
  } catch { return }
  const running = sortedInstances.value.filter(i => i.status === 'running')
  for (const instance of running) {
    try { await mccStore.stopInstance(instance.instance_id) } catch { /* skip */ }
  }
  ElMessage.success(`已停止 ${running.length} 个实例`)
}

async function forceKillAll() {
  try {
    await ElMessageBox.confirm(
      `⚠️ 将立即强制终止服务器上所有 MCC 进程！\n\n包括：正在运行的实例 + 后端重启后残留的孤儿进程。`,
      '强制终止所有进程',
      { type: 'error', confirmButtonText: '确认终止', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    const result = await mccStore.killAllInstances()
    ElMessage.success(`已强制终止 ${result.killed} 个进程`)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  }
}

// Bot connect / disconnect
async function handleConnect(instance: MccInstance) {
  let bot = getBot(instance)
  // 如果还没有 Bot 记录，自动注册
  if (!bot) {
    try {
      bot = await botStore.createBot({
        bot_id: instance.slug,
        name: instance.display_name || instance.slug,
        mc_username: instance.mc_username || '',
      } as any)
      // 关联到实例
      await mccInstanceApi.update(instance.instance_id, { bot_id: instance.slug })
      instance.bot_id = instance.slug
    } catch {
      ElMessage.error('Bot 自动注册失败')
      return
    }
  }
  const config: any = {}
  if (instance.mcp_host) config.host = instance.mcp_host
  if (instance.mcp_port) config.port = instance.mcp_port
  const result = await botStore.connectBot(bot!.bot_id, config)
  const newStatus = result?.status || ''
  if (newStatus === 'online') {
    ElMessage.success('Bot 已连接')
  } else if (newStatus === 'error') {
    ElMessage.error('连接失败：MCC MCP 服务器未响应。请确认 MCC 已进入 MC 游戏且 MCP 已启用')
  } else {
    ElMessage.warning('连接状态：' + newStatus)
  }
}

async function handleDisconnect(instance: MccInstance) {
  const bot = getBot(instance)
  if (!bot) return
  await botStore.disconnectBot(bot.bot_id)
  ElMessage.success('已断开')
}

async function toggleReconnect(instance: MccInstance, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  try {
    await mccInstanceApi.update(instance.instance_id, { auto_reconnect: checked })
    instance.auto_reconnect = checked
  } catch {
    ElMessage.error('更新失败')
  }
}

async function handleRestart(instance: MccInstance) {
  await ElMessageBox.confirm('配置已保存后通常需要重启 MCC 才会生效，确认重启？', '重启确认', { type: 'warning' })
  await handleStop(instance)
  await handleStart(instance)
}

async function handleDelete(instance: MccInstance) {
  await ElMessageBox.confirm(`确认删除实例 ${instance.slug}？当前只软删除，不会删除目录文件。`, '删除确认', { type: 'warning' })
  // Also delete associated bot if exists
  const bot = getBot(instance)
  if (bot) {
    try { await botStore.deleteBot(bot.bot_id) } catch { /* ignore */ }
  }
  await mccStore.deleteInstance(instance.instance_id)
  ElMessage.success('实例已删除')
}

async function openInstance(instance: MccInstance, tab: 'terminal' | 'account' | 'files') {
  selectedInstance.value = instance
  activeTab.value = tab
  detailOpen.value = true
  await loadActiveTab()
}

async function loadActiveTab() {
  if (!selectedInstance.value) return
  if (activeTab.value === 'account') {
    await mccStore.fetchProfiles()
    const data = await mccStore.fetchAccountConfig(selectedInstance.value.instance_id)
    Object.assign(accountForm, { ...data, password: '' })
    selectedProfileId.value = selectedInstance.value.account_profile_id || ''
  }
  if (activeTab.value === 'inventory') {
    fetchInventory()
  }
}

async function handleTabChange() { await loadActiveTab() }

// ── Inventory ──────────────────────────────

async function fetchInventory() {
  if (!selectedInstance.value) return
  const botId = selectedInstance.value.bot_id
  if (!botId) { ElMessage.warning('此实例未绑定 Bot'); return }
  inventoryLoading.value = true
  try {
    const { data } = await botApi.getInventory(botId)
    inventoryData.value = data
  } catch (e: any) {
    ElMessage.error('获取背包失败: ' + (e?.response?.data?.detail || e))
  } finally { inventoryLoading.value = false }
}

async function handleInventoryAction(payload: { action: string; slot_id: number; inventory_id?: number }) {
  const botId = selectedInstance.value?.bot_id
  if (!botId) { ElMessage.warning('未绑定 Bot'); return }
  try {
    await botApi.inventoryAction(botId, {
      action: payload.action,
      slot_id: payload.slot_id,
      inventory_id: payload.inventory_id ?? 0,
    })
    ElMessage.success('操作完成')
    fetchInventory()
  } catch (e: any) {
    ElMessage.error('操作失败: ' + (e?.response?.data?.detail || e))
  }
}

async function handleInventoryDrop(payload: { item_type: string; count: number }) {
  const botId = selectedInstance.value?.bot_id
  if (!botId) { ElMessage.warning('未绑定 Bot'); return }
  try {
    await botApi.inventoryDrop(botId, {
      item_type: payload.item_type,
      count: payload.count,
    })
    ElMessage.success(`丢弃 ${payload.item_type} ×${payload.count}`)
    fetchInventory()
  } catch (e: any) {
    ElMessage.error('丢弃失败: ' + (e?.response?.data?.detail || e))
  }
}

async function saveAccountConfig() {
  if (!selectedInstance.value) return
  const result = await mccStore.saveAccountConfig(selectedInstance.value.instance_id, { ...accountForm })
  lastDiff.value = result.diff
  ElMessage.success(result.restart_required ? '配置已保存，建议重启 MCC 生效' : '配置已保存')
}

async function createProfile() {
  if (!profileForm.name || !profileForm.username) {
    ElMessage.warning('请填写模板名和用户名')
    return
  }
  const profile = await mccStore.createProfile({ ...profileForm })
  selectedProfileId.value = profile.profile_id
  showProfileCreate.value = false
  Object.assign(profileForm, { name: '', auth_type: 'offline', username: '', password: '', auth_server_url: '', auth_api_path: '', authlib_injector_path: '', mc_server_host: '', mc_server_port: 25565, mc_version: '1.21.1' })
  ElMessage.success('账号模板已创建')
}

async function applySelectedProfile() {
  if (!selectedInstance.value || !selectedProfileId.value) return
  const result = await mccStore.applyProfile(selectedInstance.value.instance_id, selectedProfileId.value)
  Object.assign(accountForm, { ...result.config, password: '' })
  lastDiff.value = result.diff
  ElMessage.success('账号模板已应用，建议重启 MCC 生效')
}

watch(detailOpen, (open) => {
  if (!open) selectedInstance.value = null
})

onMounted(() => refreshAll())
</script>

<style scoped>
.bots-page { display: flex; flex-direction: column; gap: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 8px; }
.page-subtitle { color: var(--text-secondary); font-size: 16px; }
.header-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.instance-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; min-height: 160px; }
.instance-card { display: flex; flex-direction: column; gap: 12px; cursor: pointer; transition: border-color 0.15s; }
.instance-card:hover { border-color: var(--border-active); }
.instance-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.instance-name { color: var(--text-primary); font-weight: bold; font-size: 16px; }
.instance-slug { color: var(--text-muted); font-size: 14px; margin-top: 4px; }
.instance-dir { color: var(--text-muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Bot status row */
.bot-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #000;
  border: 1px solid var(--border-subtle);
}
.status-dot-mini {
  width: 8px; height: 8px;
  flex-shrink: 0;
}
.status-dot-mini.online { background: #00ff00; box-shadow: 0 0 6px #00ff00; }
.status-dot-mini.warning { background: #ffff00; box-shadow: 0 0 6px #ffff00; }
.status-dot-mini.error { background: #ff0000; box-shadow: 0 0 6px #ff0000; }
.status-dot-mini.offline { background: #555; }
.bot-status-label { font-family: var(--font-body); font-size: 13px; color: var(--text-secondary); }
.bot-server { font-size: 13px; color: var(--text-muted); margin-left: auto; }

/* HP / Food bars */
.bot-bars { display: flex; flex-direction: column; gap: 8px; }
.bar-row { display: flex; align-items: center; gap: 8px; }
.bar-label { font-family: var(--font-mono); font-size: 12px; width: 20px; flex-shrink: 0; }
.bar-label.hp { color: #ff0000; }
.bar-label.fd { color: #ffff00; }
.bar-val { font-size: 12px; color: var(--text-secondary); width: 32px; text-align: right; }
.pixel-progress { flex: 1; height: 10px; background: #111; border: 1px solid var(--border-subtle); overflow: hidden; }
.pixel-progress-fill { height: 100%; }
.pixel-progress-fill.red { background: #cc0000; }
.pixel-progress-fill.yellow { background: #ccaa00; }

.actions { display: flex; flex-wrap: wrap; gap: 10px; }
.actions .pixel-btn { padding: 8px 14px; }
.terminal-link { text-decoration: none; display: inline-flex; align-items: center; }
.pixel-btn.outline.active { border-color: var(--green-primary); color: var(--green-primary); background: var(--green-glow); }
.pixel-btn:disabled { opacity: .45; cursor: not-allowed; }
.pixel-badge.muted { opacity: .6; }
.reconnect-toggle { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; padding: 4px 8px; border: 1px solid var(--border-subtle); background: #000; }
.reconnect-toggle input { accent-color: var(--green-primary); }
.toggle-label { font-size: 12px; color: var(--text-secondary); }
.empty-text { grid-column: 1 / -1; color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
.detail-panel { height: 100%; display: flex; flex-direction: column; gap: 12px; }
.terminal-meta { display: flex; flex-wrap: wrap; gap: 20px; color: var(--text-secondary); font-size: 14px; margin-bottom: 12px; }
.account-toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
.account-toolbar .el-select { width: 360px; }
.account-form { max-width: 760px; }

/* ============ RESPONSIVE ============ */
@media (max-width: 1024px) {
  .instance-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .bots-page { gap: 16px; }
  .page-header { flex-direction: column; align-items: stretch; gap: 12px; }
  .page-title { font-size: 14px; }
  .page-subtitle { font-size: 14px; }
  .header-actions { justify-content: flex-start; }
  .header-actions .pixel-btn { flex: 1; text-align: center; }
  .instance-name { font-size: 14px; }
  .instance-slug { font-size: 12px; }
  .instance-dir { font-size: 12px; }
  .actions { gap: 8px; }
  .actions .pixel-btn { font-size: 12px; padding: 6px 12px; min-height: 40px; }
  .account-toolbar { flex-direction: column; align-items: stretch; }
  .account-toolbar .el-select { width: 100%; }
  .account-form { max-width: 100%; }
  .terminal-meta { font-size: 12px; gap: 10px; }
}
@media (max-width: 480px) {
  .actions .pixel-btn { flex: 1 1 45%; font-size: 11px; }
}
</style>
