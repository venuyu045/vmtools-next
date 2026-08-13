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

    <!-- 定时任务（2026-08-13） -->
    <div class="sched-section">
      <div class="sched-head">
        <div>
          <h3 class="pixel sched-title">定时任务</h3>
          <div class="mono sched-sub">
            自定义<b>何时</b>、哪些 <b>bot</b> 去完成什么<b>任务</b>，到点自动调度执行；
            被标记「工作中」的 bot 会自动跳过（不派活）。记录只保留 7 天。
          </div>
        </div>
        <button class="pixel-btn" @click="openCreate">+ 新建定时任务</button>
      </div>

      <div v-loading="schedLoading" class="sched-wrap">
        <table class="bot-table sched-table">
          <thead>
            <tr>
              <th>任务名称</th>
              <th>类型</th>
              <th>目标</th>
              <th>调度时间</th>
              <th>Bot</th>
              <th>启用</th>
              <th>上次执行</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in scheduled" :key="t.id">
              <td class="bot-id">{{ t.name }}</td>
              <td><span class="sched-type" :class="t.task_type">{{ schedTypeLabel(t.task_type) }}</span></td>
              <td>{{ t.target_name || t.target_id }}</td>
              <td class="mono">{{ t.schedule_text }}</td>
              <td class="mono sched-bots">{{ (t.bot_ids || []).join('、') }}</td>
              <td><el-switch :model-value="t.enabled" size="small" @change="(v: string | number | boolean) => toggleScheduled(t, !!v)" /></td>
              <td class="mono">{{ t.last_run_at ? fmtShort(t.last_run_at) : '—' }}</td>
              <td><button class="pixel-btn mini danger" @click="delScheduled(t)">删除</button></td>
            </tr>
            <tr v-if="!scheduled.length && !schedLoading">
              <td colspan="8" class="empty-text">-- 暂无定时任务，点击右上角「+ 新建定时任务」创建 --</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新建定时任务对话框 -->
    <el-dialog v-model="dialogVisible" title="新建定时任务" width="520px" :close-on-click-modal="false">
      <el-form label-width="90px" label-position="left">
        <el-form-item label="任务名称" required>
          <el-input v-model="form.name" placeholder="如：每日 14:30 扫描主仓库" />
        </el-form-item>
        <el-form-item label="任务类型" required>
          <el-select v-model="form.task_type" style="width: 100%" @change="onTypeChange">
            <el-option label="仓库扫描" value="scan" />
            <el-option label="物流任务" value="logistics" />
            <el-option label="地图画（启动已建任务）" value="map_art" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标" required>
          <el-select v-model="form.target_id" filterable style="width: 100%" :placeholder="targetPlaceholder">
            <el-option v-for="o in targetOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度方式" required>
          <el-radio-group v-model="form.schedule_kind">
            <el-radio value="once">一次性</el-radio>
            <el-radio value="daily">每天</el-radio>
            <el-radio value="weekly">每周</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.schedule_kind === 'once'" label="执行时间" required>
          <el-date-picker
            v-model="form.run_at"
            type="datetime"
            placeholder="选择日期时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item v-else label="执行时间" required>
          <el-select v-if="form.schedule_kind === 'weekly'" v-model="form.schedule_weekday" style="width: 140px; margin-right: 8px">
            <el-option v-for="(w, i) in weekdays" :key="i" :label="w" :value="i" />
          </el-select>
          <el-time-select
            v-model="form.schedule_time"
            start="00:00"
            step="00:05"
            end="23:59"
            placeholder="HH:MM"
            style="width: 140px"
          />
        </el-form-item>
        <el-form-item label="执行 Bot" required>
          <el-select v-model="form.bot_ids" multiple filterable style="width: 100%" placeholder="选择 MF bot（可多选）">
            <el-option v-for="b in bots" :key="b.bot_id" :label="`${b.bot_id}（${b.name}）`" :value="b.bot_id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <button class="pixel-btn outline" @click="dialogVisible = false">取消</button>
        <button class="pixel-btn" :disabled="savingSched" @click="submitScheduled">创建</button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tasksApi } from '@/api/tasks'
import { warehouseApi } from '@/api/warehouse'
import { logisticsApi } from '@/api/logistics'
import { mapArtApi } from '@/api/mapArt'

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

interface ScheduledRow {
  id: string
  name: string
  task_type: string
  target_id: string
  target_name: string
  bot_ids: string[]
  schedule_kind: string
  schedule_text: string
  enabled: boolean
  last_run_at: string | null
}

const loading = ref(false)
const bots = ref<ManualWorkRow[]>([])

// ── 定时任务（2026-08-13） ──
const schedLoading = ref(false)
const scheduled = ref<ScheduledRow[]>([])
const dialogVisible = ref(false)
const savingSched = ref(false)
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const targetOptions = ref<{ value: string; label: string }[]>([])
const form = ref({
  name: '',
  task_type: 'scan',
  target_id: '',
  bot_ids: [] as string[],
  schedule_kind: 'daily',
  run_at: null as string | null,
  schedule_time: '14:30',
  schedule_weekday: 0,
})

const targetPlaceholder = () =>
  ({ scan: '选择要扫描的仓库', logistics: '选择物流模板', map_art: '选择要启动的地图画任务' })[form.value.task_type] || ''

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

// ── 定时任务逻辑 ──
function schedTypeLabel(t: string): string {
  return { scan: '仓库扫描', logistics: '物流', map_art: '地图画' }[t] || t
}

function fmtShort(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function loadScheduled() {
  schedLoading.value = true
  try {
    const resp = await tasksApi.listScheduled()
    scheduled.value = resp.data?.tasks || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '定时任务加载失败')
  } finally {
    schedLoading.value = false
  }
}

async function onTypeChange() {
  form.value.target_id = ''
  targetOptions.value = []
  try {
    if (form.value.task_type === 'scan') {
      const resp = await warehouseApi.list()
      const list = resp.data || (Array.isArray(resp.data) ? resp.data : resp.data?.warehouses || [])
      targetOptions.value = (Array.isArray(list) ? list : []).map((w: any) => ({
        value: w.warehouse_id,
        label: w.name || w.warehouse_id,
      }))
    } else if (form.value.task_type === 'logistics') {
      const resp = await logisticsApi.listTemplates({ page: 1, page_size: 200 })
      const list = resp.data?.items || resp.data?.templates || resp.data || []
      targetOptions.value = (Array.isArray(list) ? list : []).map((t: any) => ({
        value: t.template_id,
        label: t.name || t.template_id,
      }))
    } else {
      const resp = await mapArtApi.listTasks()
      const list = resp.data?.tasks || resp.data || []
      targetOptions.value = (Array.isArray(list) ? list : []).map((t: any) => ({
        value: t.task_id,
        label: `${t.name || t.task_id}（${t.status || '?'}）`,
      }))
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '目标选项加载失败')
  }
}

function openCreate() {
  form.value = {
    name: '',
    task_type: 'scan',
    target_id: '',
    bot_ids: [],
    schedule_kind: 'daily',
    run_at: null,
    schedule_time: '14:30',
    schedule_weekday: 0,
  }
  dialogVisible.value = true
  onTypeChange()
}

async function submitScheduled() {
  const f = form.value
  if (!(f.name || '').trim()) return ElMessage.warning('请填写任务名称')
  if (!f.target_id) return ElMessage.warning('请选择任务目标')
  if (!f.bot_ids.length) return ElMessage.warning('请至少选择一个 bot')
  if (f.schedule_kind === 'once' && !f.run_at) return ElMessage.warning('请选择一次性执行时间')
  if (f.schedule_kind !== 'once' && !f.schedule_time) return ElMessage.warning('请选择执行时间')
  savingSched.value = true
  try {
    await tasksApi.createScheduled({
      name: f.name.trim(),
      task_type: f.task_type,
      target_id: f.target_id,
      bot_ids: f.bot_ids,
      schedule_kind: f.schedule_kind,
      run_at: f.run_at,
      schedule_time: f.schedule_kind === 'once' ? '' : f.schedule_time,
      schedule_weekday: f.schedule_weekday,
    })
    ElMessage.success('定时任务已创建')
    dialogVisible.value = false
    await loadScheduled()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    savingSched.value = false
  }
}

async function toggleScheduled(t: ScheduledRow, val: boolean) {
  try {
    await tasksApi.updateScheduled(t.id, { enabled: val })
    t.enabled = val
    ElMessage.success(val ? '已启用' : '已停用')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function delScheduled(t: ScheduledRow) {
  try {
    await ElMessageBox.confirm(`确认删除定时任务「${t.name}」？`, '确认', { type: 'warning' })
    await tasksApi.deleteScheduled(t.id)
    ElMessage.success('已删除')
    await loadScheduled()
  } catch { /* 取消 */ }
}

onMounted(() => {
  load()
  loadScheduled()
})
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
.pixel-btn.danger { color: #f56c6c; border-color: rgba(245, 108, 108, 0.5); }
.pixel-btn.danger:hover { background: rgba(245, 108, 108, 0.1); }

/* 定时任务（2026-08-13） */
.sched-section { display: flex; flex-direction: column; gap: 12px; }
.sched-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.sched-title { color: var(--accent); font-size: 15px; margin: 0 0 4px; }
.sched-sub { color: var(--text-muted); font-size: 12px; line-height: 1.6; }
.sched-sub b { color: var(--text-primary); }
.sched-wrap { border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); overflow: hidden; background: var(--bg-card); }
.sched-table td { font-size: 12px; }
.sched-type { font-size: 10px; font-weight: 700; padding: 1px 8px; border-radius: 999px; white-space: nowrap; }
.sched-type.scan { background: rgba(64, 158, 255, 0.15); color: #409eff; }
.sched-type.logistics { background: rgba(108, 122, 140, 0.15); color: #6c7a8c; }
.sched-type.map_art { background: rgba(217, 119, 87, 0.15); color: var(--accent); }
.sched-bots { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>