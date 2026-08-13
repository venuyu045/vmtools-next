<template>
  <div class="task-manage">
    <div class="page-header">
      <div>
        <h2 class="pixel page-title">任务管理</h2>
        <div class="mono page-subtitle">
          自定义 MF 正在干什么（工作名称 + 是否工作中）。手动标记的工作<strong>跨上下线保持</strong>；
          被标记「工作中」的 bot <strong>不会被自动调度派活</strong>（地图画 / 物流 / 仓库扫描都会跳过它）。
        </div>
      </div>
      <button class="pixel-btn outline" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-loading="loading" class="bot-table-wrap">
      <div v-if="bots.length === 0 && !loading" class="empty-text mono">-- 暂无 MF bot（需先在 MF 管理页创建实例并分配 bot_id）--</div>
      <table v-else class="bot-table">
        <thead>
          <tr>
            <th>Bot</th>
            <th>状态</th>
            <th>当前系统工作</th>
            <th>工作名称（标记时必填）</th>
            <th>工作中</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in bots" :key="b.bot_id">
            <td>
              <div class="bot-id">{{ b.bot_id }}</div>
              <div class="bot-name">{{ b.name }}</div>
            </td>
            <td>
              <span class="status-badge" :class="b.status">{{ statusLabel(b.status) }}</span>
            </td>
            <td>
              <span v-if="b.system_task" class="sys-task" :class="b.system_task.type">
                <template v-if="b.system_task.type === 'logistics'">物流</template>
                <template v-else-if="b.system_task.type === 'mapart'">地图画</template>
                <template v-else-if="b.system_task.type === 'scan'">仓库扫描</template>
                <template v-else>{{ b.system_task.name }}</template>
                <span class="sys-task-name">· {{ b.system_task.name }}</span>
              </span>
              <span v-else class="muted-text">空闲</span>
            </td>
            <td>
              <el-input
                v-model="b.nameInput"
                placeholder="输入自定义工作名称（如：挂机farm、刷铁机…）"
                clearable
                style="width: 100%"
                size="small"
                @input="(v: string) => b.nameInput = v || ''"
              />
            </td>
            <td>
              <el-switch
                :model-value="b.working"
                :loading="b.saving"
                :disabled="b.saving"
                @change="(v: string | number | boolean) => toggleWork(b, !!v)"
              />
            </td>
            <td>
              <button
                class="pixel-btn mini"
                :disabled="!b.working || !(b.nameInput || '').trim() || b.saving"
                @click="save(b)"
              >保存</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { tasksApi } from '@/api/tasks'

interface ManualWorkRow {
  bot_id: string
  name: string
  status: string
  system_task: { type: string; name: string; status: string; progress?: number } | null
  manual: { working: boolean; name: string } | null
  // 表单态
  working: boolean
  nameInput: string
  saving: boolean
  dirty: boolean
}

const loading = ref(false)
const bots = ref<ManualWorkRow[]>([])

async function load() {
  loading.value = true
  try {
    const resp = await tasksApi.getManualWork()
    bots.value = (resp.data?.bots || []).map((b: any) => ({
      bot_id: b.bot_id,
      name: b.name,
      status: b.status,
      system_task: b.system_task || null,
      manual: b.manual || null,
      working: !!(b.manual && b.manual.working),
      nameInput: (b.manual && b.manual.name) || '',
      saving: false,
      dirty: false,
    }))
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

function statusLabel(s: string): string {
  return { online: '在线', offline: '离线', connecting: '连接中', error: '错误' }[s] || s
}

async function toggleWork(b: ManualWorkRow, val: boolean) {
  b.working = val
  if (!val) {
    // 关闭「工作中」→ 直接清除标记（无需名称）
    await save(b)
  } else {
    // 开启 → 必须填名称，否则提示并回退
    const name = (b.nameInput || '').trim()
    if (!name) {
      ElMessage.warning('开启「工作中」前请先填写工作名称')
      b.working = false
      return
    }
    await save(b)
  }
}

async function save(b: ManualWorkRow) {
  if (b.saving) return
  const name = (b.nameInput || '').trim()
  if (b.working && !name) {
    ElMessage.warning('工作名称不能为空')
    return
  }
  b.saving = true
  try {
    await tasksApi.setManualWork(b.bot_id, b.working, name)
    b.nameInput = name
    ElMessage.success(`${b.bot_id} 已${b.working ? `标记为「${name}」` : '解除工作标记'}`)
    await load() // 刷新 system_task 等
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
    b.working = !b.working // 回退
  } finally {
    b.saving = false
  }
}

onMounted(load)
</script>

<style scoped>
.task-manage { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 13px; line-height: 1.6; }
.page-subtitle strong { color: var(--accent); }

.bot-table-wrap { border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); overflow: hidden; background: var(--bg-card); }
.bot-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.bot-table th, .bot-table td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
.bot-table th { background: var(--bg-hover); font-size: 12px; color: var(--text-muted); font-weight: 600; }
.bot-table tr:last-child td { border-bottom: none; }
.bot-id { font-weight: 600; color: var(--text-primary); }
.bot-name { font-size: 11px; color: var(--text-muted); }
.status-badge { font-size: 11px; padding: 1px 8px; border-radius: 999px; }
.status-badge.online { background: rgba(103, 194, 58, 0.15); color: #67c23a; }
.status-badge.offline { background: rgba(144, 147, 153, 0.15); color: #909399; }
.status-badge.connecting { background: rgba(230, 162, 60, 0.15); color: #e6a23c; }
.status-badge.error { background: rgba(245, 108, 108, 0.15); color: #f56c6c; }
.sys-task { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: rgba(108, 122, 140, 0.12); color: #6c7a8c; }
.sys-task-name { margin-left: 4px; }
.muted-text { color: var(--text-disabled); font-size: 12px; }
.empty-text { text-align: center; padding: 24px; color: var(--text-muted); font-size: 14px; }
.pixel-btn.mini { padding: 3px 10px; font-size: 12px; }
</style>