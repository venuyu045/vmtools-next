<template>
  <div class="warehouse-editor">
    <p class="wh-desc">
      全局补货仓库：直接设定「某种材料放在哪个潜影盒」。任何地图画任务建造时，
      bot 缺该材料会自动去对应潜影盒取货（任务级配置优先于全局）。
      <strong>坐标填补货仓库所在维度的世界坐标</strong>（如仓库在下界则填下界坐标）。
    </p>

    <!-- 添加材料 -->
    <div class="add-row">
      <el-select v-model="addItemId" filterable allow-create default-first-option size="small"
                 placeholder="选择或输入材料 ID（如 white_concrete）" style="width: 300px">
        <!-- 2026-08-18：已添加配置的材料从下拉隐藏（防止重复添加） -->
        <el-option v-for="m in availableMaterials" :key="m" :label="zhItemName(m)" :value="m" />
      </el-select>
      <el-button size="small" type="primary" :disabled="!addItemId" @click="addMaterial">添加材料</el-button>
    </div>

    <!-- 材料↔坐标编辑 -->
    <div v-loading="loading" class="wh-list">
      <div v-if="!items.length && !loading" class="empty">尚未配置任何材料，先添加材料并填写潜影盒坐标</div>
      <div v-for="(it, idx) in items" :key="idx" class="wh-item">
        <div class="wh-head">
          <ItemIcon :item-id="it.item_id" :size="26" class="mat-icon" />
          <span class="wh-name">{{ zhItemName(it.item_id) }}</span>
          <span class="wh-id mono">{{ it.item_id }}</span>
          <el-button size="small" text type="primary" @click="addBox(idx)">+ 潜影盒</el-button>
          <el-button size="small" text type="danger" @click="items.splice(idx, 1)">移除</el-button>
        </div>
        <div class="wh-boxes">
          <div v-for="(b, bi) in it.boxes" :key="bi" class="wh-box">
            <span class="box-label mono">#{{ bi + 1 }}</span>
            <el-input-number v-model="b.x" :controls="false" size="small" class="box-input" placeholder="X" />
            <el-input-number v-model="b.y" :controls="false" size="small" class="box-input" placeholder="Y" />
            <el-input-number v-model="b.z" :controls="false" size="small" class="box-input" placeholder="Z" />
            <el-button size="small" text type="danger" @click="it.boxes.splice(bi, 1)">删</el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="save-bar">
      <el-button type="primary" :loading="saving" :disabled="!items.length" @click="save">保存全局仓库</el-button>
      <span class="wh-hint" v-if="savedAt">上次保存：{{ savedAt }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import ItemIcon from '@/components/ItemIcon.vue'
import { mapArtApi } from '@/api/mapArt'
import { errMsg } from '@/utils/error'
import { zhItemName } from '@/utils/itemZh'

interface Box { x: number; y: number; z: number }
interface WhItem { item_id: string; boxes: Box[] }

const loading = ref(false)
const saving = ref(false)
const savedAt = ref('')
const items = ref<WhItem[]>([])
const addItemId = ref('')
const knownMaterials = ref<string[]>([])
/** 2026-08-18：可选材料 = 已知材料 - 已添加配置的材料（下拉不再出现重复项） */
const availableMaterials = computed(() =>
  knownMaterials.value.filter(m => !items.value.some(it => it.item_id === m)))

async function load() {
  loading.value = true
  try {
    const [whResp, tasksResp] = await Promise.all([
      mapArtApi.getSupplyWarehouse(),
      mapArtApi.listTasks(),
    ])
    items.value = (whResp.data?.items || []).map((it: any) => ({
      item_id: it.item_id,
      boxes: (it.boxes || []).map((b: any) => ({ x: b.x, y: b.y, z: b.z })),
    }))
    // 从历史任务聚合已知材料（供下拉选择）
    const known = new Set<string>()
    for (const t of (tasksResp.data?.tasks || [])) {
      try {
        const { data } = await mapArtApi.getSupplyBoxes(t.task_id)
        for (const it of (data.items || [])) known.add(it.item_id)
      } catch { /* 单个任务失败忽略 */ }
    }
    for (const it of items.value) known.add(it.item_id)
    knownMaterials.value = [...known].sort()
  } catch (e) {
    ElMessage.error(errMsg(e, '加载全局仓库失败'))
  } finally {
    loading.value = false
  }
}

function addMaterial() {
  const raw = addItemId.value.trim()
  if (!raw) return
  let itemId = raw
  if (!itemId.includes(':')) itemId = `minecraft:${itemId}`
  itemId = itemId.split('[')[0]
  if (items.value.some(it => it.item_id === itemId)) {
    ElMessage.warning('该材料已存在')
    return
  }
  items.value.push({ item_id: itemId, boxes: [{ x: 0, y: 0, z: 0 }] })
  addItemId.value = ''
  if (!knownMaterials.value.includes(itemId)) knownMaterials.value.push(itemId)
}

function addBox(idx: number) { items.value[idx].boxes.push({ x: 0, y: 0, z: 0 }) }

async function save() {
  saving.value = true
  try {
    const payload = items.value
      .map(it => ({ item_id: it.item_id, boxes: it.boxes.filter(b => !(b.x === 0 && b.y === 0 && b.z === 0)) }))
      .filter(it => it.boxes.length > 0)
    await mapArtApi.saveSupplyWarehouse(payload)
    ElMessage.success('全局仓库已保存，所有地图画任务将自动按材料复用')
    savedAt.value = new Date().toLocaleTimeString()
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e, '保存全局仓库失败'))
  } finally {
    saving.value = false
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>

<style scoped>
.warehouse-editor { display: flex; flex-direction: column; gap: 10px; }
.wh-desc { font-size: 12px; color: var(--text-muted); margin: 0; line-height: 1.6; }
.add-row { display: flex; align-items: center; gap: 8px; }
.wh-list { display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow-y: auto; }
.wh-item { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 8px 10px; }
.wh-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.mat-icon { flex-shrink: 0; border-radius: 3px; }
.wh-name { font-weight: 600; font-size: 13px; }
.wh-id { font-size: 11px; color: var(--text-muted); flex: 1; overflow: hidden; text-overflow: ellipsis; }
.wh-boxes { display: flex; flex-direction: column; gap: 4px; padding-left: 34px; }
.wh-box { display: flex; align-items: center; gap: 6px; }
.box-label { width: 30px; color: var(--text-muted); font-size: 11px; }
.box-input { width: 90px; }
.save-bar { display: flex; align-items: center; gap: 10px; }
.wh-hint { font-size: 11px; color: var(--text-muted); }
.empty { color: var(--text-muted); padding: 16px 0; text-align: center; font-size: 12px; }
</style>