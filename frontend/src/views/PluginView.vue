<template>
  <div>
    <h2>MF 插件管理</h2>
    <p class="plugin-tip">
      插件体系仅服务于 <b>Mineflayer</b> 引擎的 bot（MCC 为固定 C# 客户端，不需要额外插件）。
      插件通过 MF 的 WebSocket 桥接订阅 bot 事件并执行操作。
    </p>
    <el-table :data="pluginStore.plugins" style="width: 100%; margin-top: 16px">
      <el-table-column prop="name" label="插件名称" width="180" />
      <el-table-column prop="description" label="说明" min-width="220" />
      <el-table-column prop="version" label="版本" width="90" />
      <el-table-column label="引擎" width="120">
        <template #default="{ row }">
          <el-tag type="success">{{ row.engine === 'mineflayer' ? 'mineflayer' : row.engine }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '已禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="270">
        <template #default="{ row }">
          <el-button size="small" @click="handleToggle(row)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
          <el-button size="small" type="primary" plain @click="handleConfig(row)">配置</el-button>
          <el-button size="small" @click="handleReload(row)">重载</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePluginStore } from '@/stores/plugin'
import { ElMessage } from 'element-plus'

const pluginStore = usePluginStore()
const router = useRouter()

async function handleToggle(plugin: any) {
  await pluginStore.togglePlugin(plugin.name)
  ElMessage.success(`插件已${plugin.enabled ? '禁用' : '启用'}`)
}

function handleConfig(plugin: any) {
  router.push(`/plugins/${plugin.name}/config`)
}

async function handleReload(plugin: any) {
  await pluginStore.reloadPlugin(plugin.name)
  ElMessage.success('插件已重载')
}

onMounted(() => pluginStore.fetchPlugins())
</script>

<style scoped>
.plugin-tip {
  color: var(--text-muted, #008800);
  font-size: 13px;
  margin: 8px 0 0;
  line-height: 1.6;
}
.plugin-tip b {
  color: var(--green-primary, #00ff00);
}
</style>