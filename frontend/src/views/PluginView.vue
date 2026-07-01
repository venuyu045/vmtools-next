<template>
  <div>
    <h2>插件管理</h2>
    <el-table :data="pluginStore.plugins" style="width: 100%; margin-top: 20px">
      <el-table-column prop="name" label="插件名称" />
      <el-table-column prop="version" label="版本" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '已禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" @click="handleToggle(row)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
          <el-button size="small" @click="handleReload(row)">重载</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { usePluginStore } from '@/stores/plugin'
import { ElMessage } from 'element-plus'

const pluginStore = usePluginStore()

async function handleToggle(plugin: any) {
  await pluginStore.togglePlugin(plugin.name)
  ElMessage.success(`插件已${plugin.enabled ? '禁用' : '启用'}`)
}

async function handleReload(plugin: any) {
  await pluginStore.reloadPlugin(plugin.name)
  ElMessage.success('插件已重载')
}

onMounted(() => pluginStore.fetchPlugins())
</script>
