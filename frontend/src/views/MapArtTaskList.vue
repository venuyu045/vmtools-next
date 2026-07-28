<template>
  <div class="mapart-list-page">
    <div class="page-header">
      <h2>Map Art Build Tasks</h2>
      <el-button type="primary" @click="showCreate = true">+ New Task</el-button>
    </div>

    <!-- Task list -->
    <el-table :data="tasks" stripe v-loading="loading" empty-text="No tasks">
      <el-table-column prop="task_id" label="ID" width="120" />
      <el-table-column prop="name" label="Name" />
      <el-table-column prop="status" label="Status" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Progress" width="180">
        <template #default="{ row }">
          <span>{{ row.placed_blocks }} / {{ row.total_blocks }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="projection_name" label="Projection" />
      <el-table-column label="Actions" width="160">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/map-art/${row.task_id}`)">View 3D</el-button>
          <el-button size="small" type="danger" @click="deleteTask(row.task_id)">Delete</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create dialog -->
    <el-dialog v-model="showCreate" title="New Map Art Task" width="500px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="Task Name">
          <el-input v-model="form.name" placeholder="My Map Art" />
        </el-form-item>
        <el-form-item label="Projection File">
          <el-upload
            :auto-upload="false"
            :on-change="onFileChange"
            :limit="1"
            accept=".litematic"
          >
            <el-button>Select .litematic</el-button>
          </el-upload>
          <span v-if="uploadedPath" style="color: green; font-size: 12px;">Uploaded: {{ uploadedPath }}</span>
        </el-form-item>
        <el-form-item label="Origin X">
          <el-input-number v-model="form.origin_x" :min="-30000000" :max="30000000" />
        </el-form-item>
        <el-form-item label="Origin Y">
          <el-input-number v-model="form.origin_y" :min="-64" :max="320" />
        </el-form-item>
        <el-form-item label="Origin Z">
          <el-input-number v-model="form.origin_z" :min="-30000000" :max="30000000" />
        </el-form-item>
        <el-form-item label="Bots">
          <el-select v-model="form.bot_ids" multiple placeholder="Select bots">
            <el-option
              v-for="bot in allBots"
              :key="bot.bot_id"
              :label="`${bot.name || bot.bot_id} (${bot.status || '?'})`"
              :value="bot.bot_id"
            />
          </el-select>
          <span v-if="!allBots.length" style="color: #888; font-size: 12px;">No bots loaded — check bot management</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">Cancel</el-button>
        <el-button type="primary" @click="createTask" :loading="creating">Create</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { mapArtApi } from '@/api/mapArt'
import { botApi } from '@/api/bot'
import { ElMessage, ElMessageBox } from 'element-plus'

const tasks = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const uploadedPath = ref('')
const allBots = ref<any[]>([])

const form = ref({
  name: 'My Map Art',
  origin_x: 0,
  origin_y: 64,
  origin_z: 0,
  bot_ids: [] as string[],
})

async function loadBots() {
  try {
    const { data } = await botApi.list()
    allBots.value = Array.isArray(data) ? data : (data.bots || data.items || [])
  } catch (e) {
    console.error('Failed to load bots:', e)
  }
}

function statusTag(s: string): string {
  if (s === 'running') return 'success'
  if (s === 'completed') return ''
  if (s === 'failed') return 'danger'
  if (s === 'paused') return 'warning'
  return 'info'
}

async function fetchTasks() {
  loading.value = true
  try {
    const { data } = await mapArtApi.listTasks()
    tasks.value = data.tasks || []
  } catch (e) {
    ElMessage.error('Failed to load tasks')
  } finally {
    loading.value = false
  }
}

async function onFileChange(uploadFile: any) {
  const file = uploadFile.raw
  if (!file) return
  try {
    const { data } = await mapArtApi.uploadProjection(file)
    uploadedPath.value = data.file_path
    ElMessage.success(`Projection uploaded: ${data.projection_info.total_blocks} blocks`)
  } catch (e) {
    ElMessage.error('Upload failed')
  }
}

async function createTask() {
  if (!uploadedPath.value) {
    ElMessage.warning('Please upload a .litematic file first')
    return
  }
  creating.value = true
  try {
    await mapArtApi.createTask({
      name: form.value.name || 'Untitled',
      projection_file_path: uploadedPath.value,
      origin_x: form.value.origin_x,
      origin_y: form.value.origin_y,
      origin_z: form.value.origin_z,
      bot_ids: form.value.bot_ids,
    })
    ElMessage.success('Task created!')
    showCreate.value = false
    form.value = { name: 'My Map Art', origin_x: 0, origin_y: 64, origin_z: 0, bot_ids: [] }
    uploadedPath.value = ''
    fetchTasks()
  } catch (e: any) {
    ElMessage.error(`Create failed: ${e?.response?.data?.detail || e}`)
  } finally {
    creating.value = false
  }
}

async function deleteTask(taskId: string) {
  try {
    await ElMessageBox.confirm('Delete this task?', 'Confirm', { type: 'warning' })
    await mapArtApi.deleteTask(taskId)
    ElMessage.success('Deleted')
    fetchTasks()
  } catch { /* cancelled */ }
}

onMounted(() => {
  fetchTasks()
  loadBots()
})
</script>

<style scoped>
.mapart-list-page { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
</style>
