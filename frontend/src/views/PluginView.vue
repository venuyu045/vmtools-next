<template>
  <div class="plugin-page">
    <h2 class="pixel page-title">MF 插件管理</h2>
    <p class="mono page-subtitle">
      插件体系仅服务于 <b>Mineflayer</b> 引擎的 bot（MCC 为固定 C# 客户端，不需要额外插件）。
      插件通过 MF 的 WebSocket 桥接订阅 bot 事件并执行操作。
    </p>

    <el-table
      v-loading="pluginStore.loading"
      :data="pluginStore.plugins"
      style="width: 100%; margin-top: 16px"
    >
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
      <el-table-column label="操作" width="280">
        <template #default="{ row }">
          <el-button
            size="small"
            :loading="pending.has(row.name)"
            :disabled="pending.size > 0"
            @click="handleToggle(row)"
          >
            {{ row.enabled ? '禁用' : '启用' }}
          </el-button>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="pending.size > 0"
            @click="handleConfig(row)"
          >
            配置
          </el-button>
          <el-button
            size="small"
            :loading="pending.has(row.name)"
            :disabled="pending.size > 0"
            @click="handleReload(row)"
          >
            重载
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePluginStore } from '@/stores/plugin'
import { ElMessage } from 'element-plus'

const pluginStore = usePluginStore()
const router = useRouter()
/** 正在操作中的插件名集合（防连点，操作期间整行按钮禁用） */
const pending = ref<Set<string>>(new Set())

async function handleToggle(plugin: any) {
  if (pending.value.has(plugin.name)) return
  pending.value.add(plugin.name)
  try {
    await pluginStore.togglePlugin(plugin.name)
    ElMessage.success(`插件已${plugin.enabled ? '禁用' : '启用'}`)
  } catch (e: any) {
    ElMessage.error(`操作失败：${e?.response?.data?.detail || e?.message || '未知错误'}`)
  } finally {
    pending.value.delete(plugin.name)
  }
}

function handleConfig(plugin: any) {
  router.push(`/plugins/${plugin.name}/config`)
}

async function handleReload(plugin: any) {
  if (pending.value.has(plugin.name)) return
  pending.value.add(plugin.name)
  try {
    await pluginStore.reloadPlugin(plugin.name)
    ElMessage.success('插件已重载')
  } catch (e: any) {
    ElMessage.error(`重载失败：${e?.response?.data?.detail || e?.message || '未知错误'}`)
  } finally {
    pending.value.delete(plugin.name)
  }
}

onMounted(() => pluginStore.fetchPlugins())
</script>

<style scoped>
.plugin-page {
  max-width: 1080px;
}
.page-title {
  color: var(--green-primary);
  font-size: 16px;
  margin-bottom: 4px;
}
.page-subtitle {
  color: var(--text-muted);
  font-size: 13px;
  margin-bottom: 16px;
}
.page-subtitle b {
  color: var(--green-primary);
}
</style>
