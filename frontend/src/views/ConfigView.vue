<template>
  <div class="config-page">
    <h2 class="pixel page-title">系统配置</h2>

    <el-card shadow="never" class="cfg-card">
      <template #header>
        <span class="mono cfg-header">MCC 全局配置</span>
      </template>

      <el-form :model="mccForm" label-width="150px" size="default">
        <el-form-item label="实例根目录">
          <el-input v-model="mccForm.instance_root" placeholder="/opt/vmtools/mcc-instances" />
          <div class="field-hint">所有 MCC 实例存放的根目录</div>
        </el-form-item>

        <el-form-item label="MCC 程序路径">
          <el-input v-model="mccForm.binary_path" placeholder="F:\mcc\MinecraftClient.exe" />
          <div class="field-hint">新建实例时复制的 MCC 程序源路径（Linux: .dll，Windows: .exe）</div>
        </el-form-item>

        <el-form-item label="启动命令">
          <el-input v-model="launchCommandStr" placeholder="dotnet,/opt/vmtools/mcc-runtime/MinecraftClient.dll" />
          <div class="field-hint">逗号分隔的启动命令。留空自动检测。Linux 示例: dotnet,/path/to/MinecraftClient.dll</div>
        </el-form-item>

        <el-form-item label="端口范围">
          <el-input-number v-model="mccForm.instance_start_port" :min="1024" :max="65535" />
          <span class="range-sep">—</span>
          <el-input-number v-model="mccForm.instance_end_port" :min="1024" :max="65535" />
          <div class="field-hint">MCP 端口分配范围</div>
        </el-form-item>

        <el-form-item label="最大实例数">
          <el-input-number v-model="mccForm.max_instances" :min="1" :max="100" />
        </el-form-item>

        <el-form-item label="日志保留天数">
          <el-input-number v-model="mccForm.log_retention_days" :min="1" :max="365" />
        </el-form-item>

        <el-form-item>
          <button class="pixel-btn" @click="saveMccConfig" :disabled="saving">保存配置</button>
          <button class="pixel-btn outline" style="margin-left: 10px" @click="loadMccConfig">重置</button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="cfg-card" style="margin-top: 16px">
      <template #header>
        <span class="mono cfg-header">完整配置（只读）</span>
      </template>
      <pre class="mono cfg-json">{{ JSON.stringify(configStore.config, null, 2) }}</pre>
      <el-button style="margin-top: 12px" @click="handleReload">重载配置</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useConfigStore } from '@/stores/config'
import { ElMessage } from 'element-plus'
import client from '@/api/client'

const configStore = useConfigStore()
const saving = ref(false)

const mccForm = reactive({
  instance_root: '',
  binary_path: '',
  instance_start_port: 33333,
  instance_end_port: 33352,
  max_instances: 20,
  log_retention_days: 14,
})

const launchCommandStr = ref('')

async function loadMccConfig() {
  try {
    const { data } = await client.get('/config/mcc')
    mccForm.instance_root = data.instance_root || ''
    mccForm.binary_path = data.binary_path || ''
    mccForm.instance_start_port = data.instance_start_port || 33333
    mccForm.instance_end_port = data.instance_end_port || 33352
    mccForm.max_instances = data.max_instances || 20
    mccForm.log_retention_days = data.log_retention_days || 14
    launchCommandStr.value = (data.launch_command || []).join(',')
  } catch {
    ElMessage.error('加载 MCC 配置失败')
  }
}

async function saveMccConfig() {
  saving.value = true
  try {
    const payload: Record<string, any> = {
      instance_root: mccForm.instance_root || null,
      binary_path: mccForm.binary_path || null,
      instance_start_port: mccForm.instance_start_port,
      instance_end_port: mccForm.instance_end_port,
      max_instances: mccForm.max_instances,
      log_retention_days: mccForm.log_retention_days,
    }
    const cmd = launchCommandStr.value.trim()
    if (cmd) {
      payload.launch_command = cmd.split(',').map(s => s.trim()).filter(Boolean)
    } else {
      payload.launch_command = []
    }
    await client.put('/config/mcc', payload)
    ElMessage.success('MCC 配置已保存并生效')
    await configStore.fetchConfig()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleReload() {
  await configStore.reloadConfig()
  ElMessage.success('配置已重载')
}

onMounted(() => {
  configStore.fetchConfig()
  loadMccConfig()
})
</script>

<style scoped>
.config-page { display: flex; flex-direction: column; gap: 16px; max-width: 860px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 4px; }
.cfg-header { color: var(--green-primary); font-size: 14px; }
.cfg-json { color: var(--text-secondary); white-space: pre-wrap; font-size: 13px; max-height: 600px; overflow: auto; background: #000; padding: 12px; border: 1px solid var(--border-card); }
.field-hint { color: var(--text-muted); font-size: 12px; margin-top: 3px; }
.range-sep { margin: 0 8px; color: var(--text-muted); }

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .config-page { max-width: 100%; }

  /* Reduce form label width on mobile */
  .cfg-card :deep(.el-form-item__label) {
    width: auto !important;
    padding-bottom: 4px;
  }
  .cfg-card :deep(.el-form-item__content) {
    margin-left: 0 !important;
  }
}
</style>
