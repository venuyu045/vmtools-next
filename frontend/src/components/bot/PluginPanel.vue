<template>
  <div class="plugin-panel">
    <div class="plugin-head">
      <span class="plugin-title">插件（MF 独有）</span>
      <span class="plugin-badge">{{ plugins.length }} 个</span>
    </div>
    <div class="plugin-desc">
      按 bot 控制插件开关：只对本 bot 生效（不改变全局设置）。插件监听 bot 事件并在 bot 进入服务器后自动执行。
    </div>

    <div v-loading="loading" class="plugin-list">
      <div v-if="plugins.length === 0 && !loading" class="empty-text mono">暂无可用插件</div>
      <div v-for="p in plugins" :key="p.name" class="plugin-row">
        <div class="plugin-info">
          <div class="plugin-name">
            {{ p.name }}
            <el-tag size="small" :type="p.bot_enabled ? 'success' : 'info'" class="bot-tag">
              {{ p.bot_enabled ? '本 bot 启用' : '本 bot 禁用' }}
            </el-tag>
            <el-tag size="small" type="warning" plain class="global-tag" :class="{ off: !p.enabled }">
              全局{{ p.enabled ? '启用' : '禁用' }}
            </el-tag>
          </div>
          <div class="plugin-desc-text">{{ p.description || '—' }}</div>
          <div class="plugin-meta mono">v{{ p.version }} · {{ p.engine }}</div>
        </div>
        <el-switch
          :model-value="p.bot_enabled"
          :disabled="pending.has(p.name)"
          :loading="pending.has(p.name)"
          @change="(val: string | number | boolean) => handleToggle(p, !!val)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { pluginApi } from '@/api/plugin'

interface BotPluginStatus {
  name: string
  version: string
  engine: string
  description: string
  enabled: boolean      // 全局启停
  bot_enabled: boolean  // 该 bot 实际生效
}

const props = defineProps<{ botId: string }>()

const plugins = ref<BotPluginStatus[]>([])
const loading = ref(false)
const pending = ref<Set<string>>(new Set())

async function load() {
  if (!props.botId) return
  loading.value = true
  try {
    const resp = await pluginApi.getBotPluginStatus(props.botId)
    plugins.value = resp.data?.plugins || []
  } catch (e: any) {
    ElMessage.warning(e?.response?.data?.detail || '获取插件状态失败')
  } finally {
    loading.value = false
  }
}

async function handleToggle(p: BotPluginStatus, val: boolean) {
  if (pending.value.has(p.name)) return
  pending.value.add(p.name)
  try {
    if (val) {
      await pluginApi.enablePluginForBot(p.name, props.botId)
    } else {
      await pluginApi.disablePluginForBot(p.name, props.botId)
    }
    p.bot_enabled = val
    ElMessage.success(`插件 ${p.name} 已为本 bot ${val ? '启用' : '禁用'}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    pending.value.delete(p.name)
  }
}

onMounted(load)
watch(() => props.botId, load)
</script>

<style scoped>
.plugin-panel {
  border: 1px solid var(--border-color, rgba(217, 119, 87, 0.25));
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--bg-card, #f5f3ec);
}
.plugin-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.plugin-title {
  font-family: var(--font-display, inherit);
  font-weight: 600;
}
.plugin-badge {
  font-size: 12px;
  color: var(--text-muted, #83807a);
  font-weight: 600;
}
.plugin-desc {
  font-size: 11px;
  color: var(--text-muted, #83807a);
  margin-bottom: 10px;
  line-height: 1.5;
}
.plugin-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.plugin-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--border-color, rgba(217, 119, 87, 0.2));
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-card, #f5f3ec);
}
.plugin-info {
  flex: 1;
  min-width: 0;
}
.plugin-name {
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.bot-tag { margin-right: 0; }
.global-tag.off { opacity: 0.6; }
.plugin-desc-text {
  font-size: 11px;
  color: var(--text-muted, #83807a);
  margin-top: 2px;
  line-height: 1.4;
}
.plugin-meta {
  font-size: 10px;
  color: var(--text-disabled, #b0aca4);
  margin-top: 2px;
}
.empty-text {
  padding: 16px 0;
  text-align: center;
}
</style>