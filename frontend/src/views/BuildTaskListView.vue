<template>
  <div>
    <div class="page-header">
      <button class="pixel-btn" @click="openCreateDialog">+ 新建任务</button>
    </div>
    <div v-if="buildStore.tasks.length === 0" class="empty-text mono">-- 暂无建造任务 --</div>
    <div class="task-grid">
      <BuildTaskCard
        v-for="task in buildStore.tasks"
        :key="task.task_id"
        :task="task"
        @start="handleStart"
        @pause="handlePause"
        @resume="handleResume"
        @cancel="handleCancel"
      />
    </div>

    <!-- 新建任务对话框 -->
    <el-dialog v-model="dialogVisible" title="新建建造任务" width="560px" destroy-on-close>
      <el-form :model="form" label-width="100px" label-position="right">
        <el-form-item label="选择 Bot" required>
          <el-select v-model="form.bot_id" placeholder="选择在线 Bot" style="width: 100%">
            <el-option
              v-for="bot in botStore.onlineBots"
              :key="bot.bot_id"
              :label="`${bot.name} (${bot.mc_username}@${bot.mc_server_host})`"
              :value="bot.bot_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="投影文件" required>
          <div style="display: flex; flex-direction: column; gap: 10px; width: 100%">
            <!-- 上传新文件 -->
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="1"
              accept=".litematic"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
            >
              <el-button type="primary" :loading="uploading">
                上传 .litematic 文件
              </el-button>
              <template #tip>
                <div class="el-upload__tip">支持 .litematic 格式，最大 50MB</div>
              </template>
            </el-upload>

            <!-- 或选择已上传的投影 -->
            <el-divider content-position="center">或选择已上传的投影</el-divider>
            <el-select
              v-model="form.projection_id"
              placeholder="选择已上传的投影文件"
              filterable
              clearable
              style="width: 100%"
              @change="handleProjectionSelect"
            >
              <el-option
                v-for="proj in projections"
                :key="proj.id"
                :label="`${proj.name} (${proj.total_blocks} 方块, ${proj.material_count} 种材料)`"
                :value="proj.id"
              />
            </el-select>
          </div>
        </el-form-item>

        <el-divider content-position="left">建造参数</el-divider>

        <el-form-item label="原点坐标">
          <div style="display: flex; gap: 8px">
            <el-input-number v-model="form.origin_x" :min="-30000000" :max="30000000" placeholder="X" />
            <el-input-number v-model="form.origin_y" :min="-64" :max="320" placeholder="Y" />
            <el-input-number v-model="form.origin_z" :min="-30000000" :max="30000000" placeholder="Z" />
          </div>
        </el-form-item>

        <el-form-item label="层高">
          <el-input-number v-model="form.layer_height" :min="1" :max="64" />
          <span style="margin-left: 8px; color: var(--text-muted); font-size: 12px">默认 6 (每层 6 格高)</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取 消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreate">
          创 建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useBuildStore } from '@/stores/build'
import { useBotStore } from '@/stores/bot'
import { buildApi } from '@/api/build'
import BuildTaskCard from '@/components/build/BuildTaskCard.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'

const buildStore = useBuildStore()
const botStore = useBotStore()
const route = useRoute()

const dialogVisible = ref(false)
const uploading = ref(false)
const submitting = ref(false)
const uploadRef = ref()

const form = reactive({
  bot_id: '',
  projection_id: '',
  origin_x: 0,
  origin_y: 0,
  origin_z: 0,
  layer_height: 6,
})

// 已上传的投影列表
const projections = ref<any[]>([])
// 当前选中的投影信息
const selectedFile: { ref: UploadFile | null; projectionPath: string } = reactive({
  ref: null,
  projectionPath: '',
})

function openCreateDialog() {
  // 确保数据就绪
  botStore.fetchBots()
  loadProjections()
  resetForm()
  dialogVisible.value = true
}

function resetForm() {
  form.bot_id = ''
  form.projection_id = ''
  form.origin_x = 0
  form.origin_y = 0
  form.origin_z = 0
  form.layer_height = 6
  selectedFile.ref = null
  selectedFile.projectionPath = ''
}

async function loadProjections() {
  try {
    const { data } = await buildApi.listProjections()
    projections.value = data
  } catch {
    // 忽略
  }
}

async function handleFileChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return

  if (!raw.name.endsWith('.litematic')) {
    ElMessage.warning('只支持 .litematic 文件')
    return
  }

  uploading.value = true
  try {
    const { data } = await buildApi.uploadProjection(raw)
    selectedFile.projectionPath = data.file_path || ''
    form.projection_id = '' // 清除已有选择
    ElMessage.success(`投影上传成功: ${data.name} (${data.total_blocks} 方块)`)
    loadProjections() // 刷新列表
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '上传失败'
    ElMessage.error(String(msg))
    // 清除上传列表
    uploadRef.value?.clearFiles()
  } finally {
    uploading.value = false
  }
}

function handleFileRemove() {
  selectedFile.projectionPath = ''
}

function handleProjectionSelect(projId: string) {
  if (!projId) {
    selectedFile.projectionPath = ''
    return
  }
  const proj = projections.value.find(p => p.id === projId)
  if (proj) {
    selectedFile.projectionPath = proj.file_path || ''
    // 清除上传文件列表
    uploadRef.value?.clearFiles()
  }
}

async function handleCreate() {
  if (!form.bot_id) {
    ElMessage.warning('请选择 Bot')
    return
  }
  if (!selectedFile.projectionPath) {
    ElMessage.warning('请上传投影文件或选择已有投影')
    return
  }

  submitting.value = true
  try {
    const projectionName = getProjectionName()
    await buildStore.createTask({
      bot_id: form.bot_id,
      projection_file_path: selectedFile.projectionPath,
      projection_name: projectionName,
      origin_x: form.origin_x,
      origin_y: form.origin_y,
      origin_z: form.origin_z,
      layer_height: form.layer_height,
    })
    ElMessage.success('建造任务已创建')
    dialogVisible.value = false
    buildStore.fetchTasks()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '创建失败'
    ElMessage.error(String(msg))
  } finally {
    submitting.value = false
  }
}

function getProjectionName(): string {
  if (form.projection_id) {
    const proj = projections.value.find(p => p.id === form.projection_id)
    return proj?.name || ''
  }
  return selectedFile.ref?.name || ''
}

async function handleStart(task: any) {
  try {
    await buildStore.startTask(task.task_id)
    ElMessage.success('任务已启动')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error(String(msg))
  }
}
async function handlePause(task: any) {
  try {
    await buildStore.pauseTask(task.build_task_id || task.task_id)
    ElMessage.success('任务已暂停')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '操作失败'
    ElMessage.error(String(msg))
  }
}
async function handleResume(task: any) {
  try {
    await buildStore.resumeTask(task.build_task_id || task.task_id)
    ElMessage.success('任务已恢复')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '操作失败'
    ElMessage.error(String(msg))
  }
}
async function handleCancel(task: any) {
  try {
    await ElMessageBox.confirm('确定要取消这个建造任务吗？', '确认取消', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await buildStore.cancelTask(task.build_task_id || task.task_id)
    ElMessage.success('任务已取消')
  } catch {
    // 用户取消
  }
}

onMounted(() => {
  buildStore.fetchTasks()
  botStore.fetchBots()
  if (route.query.create === '1') {
    openCreateDialog()
  }
})
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.empty-text { color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
.task-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
@media (max-width: 1000px) { .task-grid { grid-template-columns: 1fr; } }
</style>
