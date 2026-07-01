<template>
  <div class="mcc-page">
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">MCC REMOTE</h2>
        <div class="mono page-subtitle">{{ mccStore.runningCount }} running / {{ mccStore.totalCount }} instances</div>
      </div>
      <div class="header-actions">
        <button class="pixel-btn outline" @click="refreshAll">刷新</button>
        <button class="pixel-btn" @click="showCreate = true">+ 新建实例</button>
      </div>
    </div>

    <div v-loading="mccStore.loading" class="instance-grid">
      <div v-if="mccStore.instances.length === 0" class="empty-text mono">-- 暂无 MCC 实例，点击右上角新建 --</div>
      <div v-for="instance in mccStore.instances" :key="instance.instance_id" class="pixel-card instance-card">
        <div class="instance-head">
          <div>
            <div class="instance-name">{{ instance.display_name || instance.slug }}</div>
            <div class="mono instance-slug">{{ instance.slug }}</div>
          </div>
          <span :class="['pixel-badge', badgeClass(instance.status)]">
            <span class="badge-dot"></span>
            {{ instance.status }}
          </span>
        </div>

        <div class="meta-grid mono">
          <div><span>PID</span><strong>{{ instance.pid || '--' }}</strong></div>
          <div><span>MCP</span><strong>{{ instance.mcp_port }}</strong></div>
          <div><span>账号</span><strong>{{ instance.mc_username || '--' }}</strong></div>
          <div><span>服务器</span><strong>{{ serverLabel(instance) }}</strong></div>
        </div>

        <div class="instance-dir mono" :title="instance.instance_dir">{{ instance.instance_dir }}</div>

        <div class="actions">
          <button class="pixel-btn" :disabled="instance.status === 'running' || isBusy(instance.instance_id)" @click="handleStart(instance)">启动</button>
          <button class="pixel-btn warning" :disabled="instance.status !== 'running' || isBusy(instance.instance_id)" @click="handleStop(instance)">停止</button>
          <button class="pixel-btn outline" @click="openInstance(instance, 'terminal')">终端</button>
          <router-link :to="{ name: 'MccTerminal', params: { id: instance.instance_id } }" class="pixel-btn outline terminal-link">全屏终端</router-link>
          <router-link :to="{ name: 'MccFiles', params: { id: instance.instance_id } }" class="pixel-btn outline terminal-link">全屏文件</router-link>
          <button class="pixel-btn outline" @click="openInstance(instance, 'account')">账号/配置</button>
          <button class="pixel-btn outline" @click="openInstance(instance, 'files')">文件</button>
          <button class="pixel-btn danger" :disabled="instance.status === 'running'" @click="handleDelete(instance)">删除</button>
        </div>
      </div>
    </div>

    <el-dialog v-model="showCreate" title="新建 MCC 实例" width="560px">
      <el-form :model="createForm" label-width="110px">
        <el-form-item label="目录名 slug"><el-input v-model="createForm.slug" placeholder="bot-alice" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="createForm.display_name" placeholder="Alice Bot" /></el-form-item>
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
        </el-tabs>
      </div>
    </el-drawer>

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
import { useMccInstanceStore } from '@/stores/mccInstance'
import type { MccAccountConfig, MccAuthType, MccInstance } from '@/api/mccInstance'

const mccStore = useMccInstanceStore()
const showCreate = ref(false)
const showProfileCreate = ref(false)
const detailOpen = ref(false)
const activeTab = ref<'terminal' | 'account' | 'files'>('terminal')
const selectedInstance = ref<MccInstance | null>(null)
const selectedProfileId = ref('')
const lastDiff = ref('')

const createForm = reactive({
  slug: '',
  display_name: '',
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

const drawerTitle = computed(() => selectedInstance.value ? `MCC · ${selectedInstance.value.display_name || selectedInstance.value.slug}` : 'MCC')

function badgeClass(status: string): string {
  if (status === 'running') return 'green'
  if (status === 'error' || status === 'crashed') return 'red'
  if (status === 'starting' || status === 'stopping') return 'yellow'
  return 'green muted'
}

function serverLabel(instance: MccInstance): string {
  if (!instance.mc_server_host) return '--'
  return `${instance.mc_server_host}:${instance.mc_server_port}`
}

function isBusy(instanceId: string): boolean {
  return !!mccStore.actionLoading[instanceId]
}

async function refreshAll() {
  await Promise.all([mccStore.fetchInstances(), mccStore.fetchProfiles()])
}

async function handleCreate() {
  if (!createForm.slug.trim()) {
    ElMessage.warning('请输入 slug')
    return
  }
  await mccStore.createInstance({ ...createForm })
  showCreate.value = false
  Object.assign(createForm, { slug: '', display_name: '', account_profile_id: null, binary_mode: 'symlink', mc_username: '', mc_server_host: '', mc_server_port: 25565, mc_version: '1.21.1' })
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

async function handleRestart(instance: MccInstance) {
  await ElMessageBox.confirm('配置已保存后通常需要重启 MCC 才会生效，确认重启？', '重启确认', { type: 'warning' })
  await handleStop(instance)
  await handleStart(instance)
}

async function handleDelete(instance: MccInstance) {
  await ElMessageBox.confirm(`确认删除实例 ${instance.slug}？当前只软删除，不会删除目录文件。`, '删除确认', { type: 'warning' })
  await mccStore.deleteInstance(instance.instance_id)
  ElMessage.success('实例已删除')
}

async function openInstance(instance: MccInstance, tab: 'terminal' | 'account' | 'files') {
  selectedInstance.value = instance
  activeTab.value = tab
  detailOpen.value = true
  await loadActiveTab()
}

async function handleTabChange() {
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
.mcc-page { display: flex; flex-direction: column; gap: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 8px; }
.page-subtitle { color: var(--text-secondary); font-size: 16px; }
.header-actions, .account-toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.instance-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; min-height: 160px; }
.instance-card { display: flex; flex-direction: column; gap: 16px; }
.instance-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.instance-name { color: var(--text-primary); font-weight: bold; font-size: 16px; }
.instance-slug { color: var(--text-muted); font-size: 14px; margin-top: 4px; }
.meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.meta-grid div { padding: 10px; background: #000; border: 1px solid var(--border-subtle); display: flex; justify-content: space-between; gap: 8px; }
.meta-grid span { color: var(--text-muted); }
.meta-grid strong { color: var(--text-primary); font-weight: normal; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.instance-dir { color: var(--text-muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; }
.actions .pixel-btn { padding: 8px 14px; }
.terminal-link { text-decoration: none; display: inline-flex; align-items: center; }
.pixel-btn:disabled { opacity: .45; cursor: not-allowed; }
.empty-text { grid-column: 1 / -1; color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
.detail-panel { height: 100%; display: flex; flex-direction: column; gap: 12px; }
.terminal-meta { display: flex; flex-wrap: wrap; gap: 20px; color: var(--text-secondary); font-size: 14px; margin-bottom: 12px; }
.pixel-badge.muted { opacity: .6; }
.account-toolbar { margin-bottom: 16px; }
.account-toolbar .el-select { width: 360px; }
.account-form { max-width: 760px; }
</style>
