<template>
  <div class="mapart-list-page">
    <div class="page-header">
      <h2>🎨 地图画建造任务</h2>
      <el-button type="primary" @click="showCreate = true">+ 新建任务</el-button>
    </div>

    <el-table :data="tasks" stripe v-loading="loading" empty-text="暂无任务">
      <el-table-column prop="task_id" label="任务ID" width="120" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="180">
        <template #default="{ row }">
          <span>{{ row.placed_blocks }} / {{ row.total_blocks }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="projection_name" label="投影" />
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/map-art/${row.task_id}`)">查看 3D</el-button>
          <el-button size="small" type="danger" @click="deleteTask(row.task_id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建任务弹窗 -->
    <el-dialog v-model="showCreate" title="新建地图画任务" width="520px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="我的地图画" />
        </el-form-item>
        <el-form-item label="投影文件">
          <el-upload :auto-upload="false" :on-change="onFileChange" :limit="1" accept=".litematic">
            <el-button>选择 .litematic 文件</el-button>
          </el-upload>
          <span v-if="uploadedPath" style="color: green; font-size: 12px;">已上传: {{ uploadedPath }}</span>
        </el-form-item>
        <el-form-item label="原点 X">
          <el-input-number v-model="form.origin_x" />
        </el-form-item>
        <el-form-item label="原点 Y">
          <el-input-number v-model="form.origin_y" />
        </el-form-item>
        <el-form-item label="原点 Z">
          <el-input-number v-model="form.origin_z" />
        </el-form-item>
        <el-form-item label="选择 Bot">
          <el-select v-model="form.bot_ids" multiple placeholder="选择参与建造的 Bot">
            <el-option
              v-for="bot in allBots"
              :key="bot.bot_id"
              :label="`${bot.name || bot.bot_id} [${botStatus(bot)}]`"
              :value="bot.bot_id"
            />
          </el-select>
          <span v-if="!allBots.length" style="color: #888; font-size: 12px;">暂无 Bot，请先在 Bot 管理中注册</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="createTask" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { mapArtApi } from '@/api/mapArt'
import { botApi } from '@/api/bot'
import { useBotStore } from '@/stores/bot'
import { ElMessage, ElMessageBox } from 'element-plus'

const botStore = useBotStore()
const tasks = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const uploadedPath = ref('')
const allBots = ref<any[]>([])

const form = ref({ name: '', origin_x: 0, origin_y: 64, origin_z: 0, bot_ids: [] as string[] })

async function loadBots() {
  try {
    // Use store (Socket.IO real-time status) + fallback to API
    await botStore.fetchBots()
    allBots.value = botStore.bots || []
    if (!allBots.value.length) {
      const { data } = await botApi.list()
      allBots.value = Array.isArray(data) ? data : (data.bots || data.items || [])
    }
  } catch (e) {
    console.error('加载 Bot 列表失败:', e)
  }
}

function botStatus(bot: any): string {
  // Socket.IO might update status to "online", DB has "error"/"offline"
  const s = bot.status || 'unknown'
  if (s === 'online') return '在线'
  if (s === 'offline') return '离线'
  if (s === 'error') return '错误'
  return s
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    draft: '草稿', pending: '待启动', running: '运行中',
    paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消'
  }
  return map[s] || s
}

function statusTag(s: string): string {
  if (s === 'running') return 'success'
  if (s === 'completed') return ''
  if (s === 'failed' || s === 'cancelled') return 'danger'
  if (s === 'paused') return 'warning'
  return 'info'
}

async function fetchTasks() {
  loading.value = true
  try {
    const { data } = await mapArtApi.listTasks()
    tasks.value = data.tasks || []
  } catch (e) {
    ElMessage.error('加载任务列表失败')
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
    ElMessage.success(`投影上传成功: ${data.projection_info.total_blocks} 个方块`)
  } catch (e) {
    ElMessage.error('上传失败')
  }
}

async function createTask() {
  if (!uploadedPath.value) { ElMessage.warning('请先上传 .litematic 投影文件'); return }
  creating.value = true
  try {
    await mapArtApi.createTask({
      name: form.value.name || '未命名',
      projection_file_path: uploadedPath.value,
      origin_x: form.value.origin_x, origin_y: form.value.origin_y, origin_z: form.value.origin_z,
      bot_ids: form.value.bot_ids,
    })
    ElMessage.success('任务创建成功！')
    showCreate.value = false
    form.value = { name: '', origin_x: 0, origin_y: 64, origin_z: 0, bot_ids: [] }
    uploadedPath.value = ''
    fetchTasks()
  } catch (e: any) {
    ElMessage.error(`创建失败: ${e?.response?.data?.detail || e}`)
  } finally { creating.value = false }
}

async function deleteTask(taskId: string) {
  try {
    await ElMessageBox.confirm('确认删除此任务？', '确认', { type: 'warning' })
    await mapArtApi.deleteTask(taskId)
    ElMessage.success('已删除')
    fetchTasks()
  } catch { /* 取消 */ }
}

onMounted(() => { fetchTasks(); loadBots() })
</script>

<style scoped>
.mapart-list-page { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; }
</style>
