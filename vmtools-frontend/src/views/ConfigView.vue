<template>
  <div>
    <h2>系统配置</h2>
    <el-card shadow="never" style="margin-top: 20px">
      <pre class="mono" style="color: var(--text-secondary); white-space: pre-wrap">{{ JSON.stringify(configStore.config, null, 2) }}</pre>
    </el-card>
    <el-button type="primary" style="margin-top: 12px" @click="handleReload">重载配置</el-button>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { ElMessage } from 'element-plus'

const configStore = useConfigStore()

async function handleReload() {
  await configStore.reloadConfig()
  ElMessage.success('配置已重载')
}

onMounted(() => configStore.fetchConfig())
</script>
