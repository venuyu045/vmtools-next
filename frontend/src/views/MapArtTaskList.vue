<template>
  <div class="mapart-list-page">
    <div class="page-header">
      <h2>地图画建造任务</h2>
      <div class="header-actions">
        <el-button @click="showTemplates = true">补货仓库</el-button>
        <el-button type="primary" @click="showCreate = true">+ 新建任务</el-button>
      </div>
    </div>

    <!-- 补货仓库（2026-08-14 三期：全局仓库为主，模板保留为备份） -->
    <el-dialog v-model="showTemplates" title="补货仓库" width="760px">
      <el-tabs>
        <el-tab-pane label="全局仓库（材料↔潜影盒）">
          <SupplyWarehouseEditor />
        </el-tab-pane>
        <el-tab-pane label="模板（备份）">
          <SupplyTemplateManager />
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

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
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click="$router.push(`/map-art/${row.task_id}`)">详情</el-button>
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
          <span v-if="uploadedPath" style="color: var(--success); font-size: 12px;">已上传: {{ uploadedPath }}</span>
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
        <el-form-item label="朝向">
          <el-select v-model="form.rotation" style="width: 100%">
            <el-option :value="0" label="0°（北 / 原方向）" />
            <el-option :value="1" label="90°（东 / 顺时针）" />
            <el-option :value="2" label="180°（南）" />
            <el-option :value="3" label="270°（西）" />
          </el-select>
          <span style="color: var(--text-muted); font-size: 12px;">投影绕 Y 轴旋转后放置在原点</span>
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
          <span v-if="!allBots.length" style="color: var(--text-muted); font-size: 12px;">暂无 Mineflayer Bot，请先在 MF 管理中创建 Mineflayer 实例并绑定 Bot</span>
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
import { useMccInstanceStore } from '@/stores/mccInstance'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errMsg } from '@/utils/error'
import SupplyTemplateManager from '@/components/build/SupplyTemplateManager.vue'
import SupplyWarehouseEditor from '@/components/build/SupplyWarehouseEditor.vue'

const botStore = useBotStore()
const mccStore = useMccInstanceStore()
const tasks = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const uploadedPath = ref('')
const allBots = ref<any[]>([])
const showTemplates = ref(false) // 补货仓库模板弹窗（2026-08-14 二期）

const form = ref({ name: '', origin_x: 0, origin_y: 64, origin_z: 0, bot_ids: [] as string[], rotation: 0 })

async function loadBots() {
  try {
    // 地图画建造使用 Mineflayer Bot：只列出 Mineflayer 引擎实例绑定的 Bot
    await Promise.all([botStore.fetchBots(), mccStore.fetchInstances()])
    allBots.value = filterMineflayerBots(botStore.bots || [])
    if (!allBots.value.length) {
      const { data } = await botApi.list()
      const fallback = Array.isArray(data) ? data : (data.bots || data.items || [])
      allBots.value = filterMineflayerBots(fallback)
    }
  } catch (e) {
    console.error('加载 Bot 列表失败:', e)
  }
}

function filterMineflayerBots(bots: any[]): any[] {
  const mfBotIds = new Set(
    mccStore.instances
      .filter(i => (i.bot_engine || '') === 'mineflayer' && i.bot_id)
      .map(i => i.bot_id as string)
  )
  return bots.filter(b => mfBotIds.has(b.bot_id))
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
    ElMessage.error(errMsg(e, '投影上传失败'))
  }
}

async function createTask() {
  if (!uploadedPath.value) { ElMessage.warning('请先上传 .litematic 投影文件'); return }
  if (!form.value.bot_ids?.length) { ElMessage.warning('请至少选择 1 个 Mineflayer Bot'); return }
  creating.value = true
  try {
    await mapArtApi.createTask({
      name: form.value.name || '未命名',
      projection_file_path: uploadedPath.value,
      origin_x: form.value.origin_x, origin_y: form.value.origin_y, origin_z: form.value.origin_z,
      bot_ids: form.value.bot_ids,
      rotation: form.value.rotation,
    })
    ElMessage.success('任务创建成功！')
    showCreate.value = false
    form.value = { name: '', origin_x: 0, origin_y: 64, origin_z: 0, bot_ids: [], rotation: 0 }
    uploadedPath.value = ''
    fetchTasks()
  } catch (e: any) {
    ElMessage.error(`创建失败：${errMsg(e, '创建任务失败')}`)
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
.header-actions { display: flex; gap: 8px; }
.page-header h2 { margin: 0; font-size: 20px; }
</style>
