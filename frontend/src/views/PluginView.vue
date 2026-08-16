<template>
  <div class="plugin-page">
    <h2 class="pixel page-title">MF 插件管理</h2>
    <p class="mono page-subtitle">
      插件体系仅服务于 <b>Mineflayer</b> 引擎的 bot（MCC 为固定 C# 客户端，不需要额外插件）。
      插件通过 MF 的 WebSocket 桥接订阅 bot 事件并执行操作。「启用 bot」列显示该插件当前
      生效于哪些 MF bot；点「bot 配置」可按 bot 单独开关（不影响全局）。
    </p>

    <el-table
      v-loading="pluginStore.loading"
      :data="pluginStore.plugins"
      style="width: 100%; margin-top: 16px"
    >
      <el-table-column prop="name" label="插件名称" width="160" />
      <el-table-column prop="description" label="说明" min-width="200" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="引擎" width="110">
        <template #default="{ row }">
          <el-tag type="success">{{ row.engine === 'mineflayer' ? 'mineflayer' : row.engine }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '已禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用 bot" min-width="160">
        <template #default="{ row }">
          <div class="bot-cell">
            <template v-if="row.bots && row.bots.length > 0">
              <el-tag
                v-for="b in row.bots"
                :key="b.bot_id"
                size="small"
                class="bot-tag"
                :type="b.bot_enabled ? 'success' : 'info'"
                effect="plain"
              >
                {{ b.bot_id }}
              </el-tag>
            </template>
            <span v-else class="mono bot-empty">（无 MF bot）</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300">
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
            @click="openBotConfig(row)"
          >
            bot 配置
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

    <!-- 按 bot 配置插件弹窗（2026-08-13）：查看/配置哪些 bot 启用了此插件 -->
    <el-dialog v-model="botConfigOpen" :title="`插件 ${botConfigPlugin?.name || ''} · bot 配置`" width="480px">
      <p class="mono bot-dialog-desc">
        每个 bot 单独开关（写入 plugin_bot_states，仅对该 bot 生效，不影响全局设置）。
        无记录的 bot 自动跟随全局{{ botConfigPlugin?.enabled ? '（已启用）' : '（已禁用）' }}。
      </p>
      <div v-loading="botConfigLoading" class="bot-config-list">
        <div v-if="(!botConfigPlugin?.bots || botConfigPlugin.bots.length === 0) && !botConfigLoading" class="empty-text mono">
          暂无 MF bot（需先在 MF 管理页创建实例并分配 bot_id）
        </div>
        <div v-for="b in botConfigPlugin?.bots || []" :key="b.bot_id" class="bot-config-row">
          <span class="mono bot-config-id">{{ b.bot_id }}</span>
          <el-tag size="small" :type="b.bot_enabled ? 'success' : 'info'" effect="plain">
            {{ b.bot_enabled ? '已启用' : '已禁用' }}
          </el-tag>
          <el-switch
            :model-value="b.bot_enabled"
            :disabled="botPending.has(b.bot_id)"
            :loading="botPending.has(b.bot_id)"
            @change="(val: string | number | boolean) => handleBotToggle(b, !!val)"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="botConfigOpen = false">关闭</el-button>
        <el-button type="primary" @click="refreshBots">刷新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePluginStore, type Plugin, type PluginBotState } from '@/stores/plugin'
import { pluginApi } from '@/api/plugin'
import { ElMessage } from 'element-plus'
import { errMsg } from '@/utils/error'

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
    ElMessage.error(errMsg(e, '操作失败'))
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
    ElMessage.error(errMsg(e, '重载失败'))
  } finally {
    pending.value.delete(plugin.name)
  }
}

// ── 按 bot 配置插件（2026-08-13） ──
const botConfigOpen = ref(false)
const botConfigLoading = ref(false)
const botConfigPlugin = ref<Plugin | null>(null)
const botPending = ref<Set<string>>(new Set())

function openBotConfig(plugin: Plugin) {
  botConfigPlugin.value = plugin
  botConfigOpen.value = true
}

async function refreshBots() {
  if (!botConfigPlugin.value) return
  botConfigLoading.value = true
  try {
    await pluginStore.fetchPlugins()
    const updated = pluginStore.plugins.find(p => p.name === botConfigPlugin.value?.name)
    if (updated) botConfigPlugin.value = updated
  } catch (e: any) {
    ElMessage.error(errMsg(e, '刷新失败'))
  } finally {
    botConfigLoading.value = false
  }
}

async function handleBotToggle(b: PluginBotState, val: boolean) {
  if (!botConfigPlugin.value) return
  if (botPending.value.has(b.bot_id)) return
  botPending.value.add(b.bot_id)
  try {
    if (val) {
      await pluginApi.enablePluginForBot(botConfigPlugin.value.name, b.bot_id)
    } else {
      await pluginApi.disablePluginForBot(botConfigPlugin.value.name, b.bot_id)
    }
    b.bot_enabled = val
    ElMessage.success(`bot ${b.bot_id} 已${val ? '启用' : '禁用'} ${botConfigPlugin.value.name}`)
  } catch (e: any) {
    ElMessage.error(errMsg(e, '操作失败'))
  } finally {
    botPending.value.delete(b.bot_id)
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
.bot-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.bot-tag {
  margin-right: 0;
}
.bot-empty {
  font-size: 12px;
  color: var(--text-disabled, #b0aca4);
}
.bot-dialog-desc {
  font-size: 12px;
  color: var(--text-muted, #83807a);
  margin-bottom: 10px;
  line-height: 1.5;
}
.bot-config-list {
  max-height: 360px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bot-config-row {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border-color, rgba(217, 119, 87, 0.2));
  border-radius: 8px;
  padding: 6px 10px;
}
.bot-config-id {
  flex: 1;
  font-size: 13px;
}
.empty-text {
  padding: 16px 0;
  text-align: center;
  font-size: 12px;
}

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .plugin-page :deep(.el-table__body td:last-child) { white-space: normal; }
  .plugin-page :deep(.el-table__body td:last-child .el-button) { margin-bottom: 6px; }
  .plugin-page :deep(.el-table__body td:last-child .el-button + .el-button) { margin-left: 0; }
}
</style>