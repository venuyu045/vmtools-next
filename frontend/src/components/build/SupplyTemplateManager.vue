<template>
  <div class="template-manager">
    <!-- 新建模板：从任务导入 或 手动配置 -->
    <el-card class="tpl-card" header="新建模板（从任务导入配置）">
      <div class="new-row">
        <el-input v-model="newName" placeholder="模板名称（如：混凝土补货）" size="small" style="width: 220px" />
        <el-select v-model="importTaskId" size="small" placeholder="选择源任务" style="width: 220px">
          <el-option v-for="t in tasks" :key="t.task_id" :label="`${t.name}（${t.task_id}）`" :value="t.task_id" />
        </el-select>
        <el-button type="primary" size="small" :disabled="!newName.trim() || !importTaskId" :loading="creating" @click="createFromTask">
          保存为模板
        </el-button>
        <span class="tpl-hint">从源任务的潜影盒配置生成模板（仅含已配置坐标的材料）</span>
      </div>
    </el-card>

    <!-- 模板列表 -->
    <el-card class="tpl-card" header="补货潜影盒模板">
      <div v-loading="loading" class="tpl-list">
        <div v-if="!templates.length && !loading" class="empty">暂无模板，先在上面新建一个</div>
        <div v-for="t in templates" :key="t.id" class="tpl-row">
          <div class="tpl-info">
            <span class="tpl-name">{{ t.name }}</span>
            <span class="tpl-meta mono">{{ t.material_count }} 种材料</span>
          </div>
          <div class="tpl-actions">
            <el-button size="small" type="primary" plain @click="openEdit(t)">编辑</el-button>
            <el-button size="small" :disabled="!t.id" @click="openApply(t)">应用</el-button>
            <el-button size="small" type="danger" plain @click="remove(t)">删除</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 应用模板到任务 -->
    <el-dialog v-model="applyOpen" :title="`应用模板「${applyingTpl?.name || ''}」到任务`" width="420px" append-to-body>
      <p class="tpl-desc">仅导入目标任务需要的材料；将覆盖目标任务当前的潜影盒配置。</p>
      <el-select v-model="applyTaskId" placeholder="选择目标任务" style="width: 100%">
        <el-option v-for="t in tasks" :key="t.task_id" :label="`${t.name}（${t.task_id}）`" :value="t.task_id" />
      </el-select>
      <template #footer>
        <el-button @click="applyOpen = false">取消</el-button>
        <el-button type="primary" :disabled="!applyTaskId" :loading="applying" @click="doApply">应用</el-button>
      </template>
    </el-dialog>

    <!-- 编辑模板（名称 + 材料坐标） -->
    <el-dialog v-model="editOpen" :title="`编辑模板「${editTpl?.name || ''}」`" width="640px" append-to-body>
      <el-input v-model="editName" placeholder="模板名称" size="small" style="margin-bottom: 10px" />
      <div class="edit-list">
        <div v-for="(it, idx) in editItems" :key="idx" class="edit-item">
          <div class="edit-head">
            <ItemIcon :item-id="it.item_id" :size="22" class="mat-icon" />
            <span class="edit-name">{{ zhItemName(it.item_id) }}</span>
            <el-button size="small" text type="primary" @click="addEditBox(idx)">+ 坐标</el-button>
            <el-button size="small" text type="danger" @click="editItems.splice(idx, 1)">移除材料</el-button>
          </div>
          <div class="edit-boxes">
            <div v-for="(b, bi) in it.boxes" :key="bi" class="edit-box">
              <el-input-number v-model="b.x" :controls="false" size="small" class="box-input" placeholder="X" />
              <el-input-number v-model="b.y" :controls="false" size="small" class="box-input" placeholder="Y" />
              <el-input-number v-model="b.z" :controls="false" size="small" class="box-input" placeholder="Z" />
              <el-button size="small" text type="danger" @click="it.boxes.splice(bi, 1)">删</el-button>
            </div>
          </div>
        </div>
        <el-button size="small" text type="primary" @click="addMaterial">+ 添加材料</el-button>
      </div>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ItemIcon from '@/components/ItemIcon.vue'
import { mapArtApi } from '@/api/mapArt'
import { errMsg } from '@/utils/error'
import { zhItemName } from '@/utils/itemZh'

const props = defineProps<{ taskId?: string }>()

interface Box { x: number; y: number; z: number }
interface TemplateItem { item_id: string; boxes: Box[] }
interface Template { id: number; name: string; material_count: number; items: TemplateItem[]; created_at?: string }

const loading = ref(false)
const creating = ref(false)
const applying = ref(false)
const savingEdit = ref(false)
const templates = ref<Template[]>([])
const tasks = ref<any[]>([])
const newName = ref('')
const importTaskId = ref(props.taskId || '')
const applyOpen = ref(false)
const applyTaskId = ref('')
const applyingTpl = ref<Template | null>(null)
const editOpen = ref(false)
const editTpl = ref<Template | null>(null)
const editName = ref('')
const editItems = ref<TemplateItem[]>([])

async function loadTasks() {
  try {
    const { data } = await mapArtApi.listTasks()
    tasks.value = data.tasks || []
  } catch { /* 忽略 */ }
}

async function loadTemplates() {
  loading.value = true
  try {
    const { data } = await mapArtApi.listSupplyTemplates()
    templates.value = (data.templates || []).map((t: any) => ({
      ...t,
      items: t.items || [],
    }))
  } catch (e) {
    ElMessage.error(errMsg(e, '加载模板失败'))
  } finally {
    loading.value = false
  }
}

async function createFromTask() {
  creating.value = true
  try {
    const { data } = await mapArtApi.getSupplyBoxes(importTaskId.value)
    const items = (data.items || [])
      .filter((it: any) => it.boxes && it.boxes.length > 0)
      .map((it: any) => ({ item_id: it.item_id, boxes: it.boxes }))
    await mapArtApi.createSupplyTemplate(newName.value.trim(), items)
    ElMessage.success('模板已创建')
    newName.value = ''
    loadTemplates()
  } catch (e) {
    ElMessage.error(errMsg(e, '创建模板失败'))
  } finally {
    creating.value = false
  }
}

function openApply(t: Template) {
  applyingTpl.value = t
  applyTaskId.value = props.taskId || ''
  applyOpen.value = true
}

async function doApply() {
  if (!applyingTpl.value || !applyTaskId.value) return
  applying.value = true
  try {
    const resp = await mapArtApi.applySupplyTemplate(applyingTpl.value.id, applyTaskId.value)
    ElMessage.success(`已应用，导入 ${resp.data?.saved ?? 0} 个潜影盒坐标`)
    applyOpen.value = false
    // 若应用到当前详情页任务，通知刷新
    if (applyTaskId.value === props.taskId) emit('applied')
  } catch (e) {
    ElMessage.error(errMsg(e, '应用模板失败'))
  } finally {
    applying.value = false
  }
}

async function remove(t: Template) {
  try {
    await ElMessageBox.confirm(`确认删除模板「${t.name}」？`, '删除模板', { type: 'warning' })
  } catch { return }
  try {
    await mapArtApi.deleteSupplyTemplate(t.id)
    ElMessage.success('模板已删除')
    loadTemplates()
  } catch (e) {
    ElMessage.error(errMsg(e, '删除模板失败'))
  }
}

// ── 编辑 ──
function openEdit(t: Template) {
  editTpl.value = t
  editName.value = t.name
  editItems.value = JSON.parse(JSON.stringify(t.items || [])) as TemplateItem[]
  editOpen.value = true
}
function addEditBox(idx: number) { editItems.value[idx].boxes.push({ x: 0, y: 0, z: 0 }) }
function addMaterial() { editItems.value.push({ item_id: 'minecraft:white_concrete', boxes: [{ x: 0, y: 0, z: 0 }] }) }
async function saveEdit() {
  if (!editTpl.value) return
  savingEdit.value = true
  try {
    const items = editItems.value
      .map(it => ({ ...it, boxes: it.boxes.filter(b => !(b.x === 0 && b.y === 0 && b.z === 0)) }))
      .filter(it => it.boxes.length > 0)
    await mapArtApi.updateSupplyTemplate(editTpl.value.id, editName.value.trim() || editTpl.value.name, items)
    ElMessage.success('模板已更新')
    editOpen.value = false
    loadTemplates()
  } catch (e) {
    ElMessage.error(errMsg(e, '保存模板失败'))
  } finally {
    savingEdit.value = false
  }
}

const emit = defineEmits<{ applied: [] }>()

onMounted(() => { loadTemplates(); loadTasks() })
defineExpose({ reload: loadTemplates })
</script>

<style scoped>
.template-manager { display: flex; flex-direction: column; gap: 12px; }
.tpl-card { flex-shrink: 0; }
.new-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tpl-hint { font-size: 11px; color: var(--text-muted); }
.tpl-list { display: flex; flex-direction: column; gap: 6px; max-height: 360px; overflow-y: auto; }
.tpl-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; padding: 8px 10px;
  border: 1px solid var(--border-subtle); border-radius: 8px;
}
.tpl-info { display: flex; align-items: center; gap: 10px; min-width: 0; }
.tpl-name { font-weight: 600; font-size: 13px; }
.tpl-meta { font-size: 11px; color: var(--text-muted); }
.tpl-actions { display: flex; gap: 4px; flex-shrink: 0; }
.tpl-desc { font-size: 12px; color: var(--text-muted); margin: 0 0 10px; }
.edit-list { max-height: 380px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.edit-item { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 8px; }
.edit-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.mat-icon { flex-shrink: 0; border-radius: 3px; }
.edit-name { flex: 1; font-size: 13px; }
.edit-boxes { display: flex; flex-direction: column; gap: 4px; padding-left: 30px; }
.edit-box { display: flex; align-items: center; gap: 6px; }
.box-input { width: 90px; }
.empty { color: var(--text-muted); padding: 16px 0; text-align: center; font-size: 12px; }
</style>