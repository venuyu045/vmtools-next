<template>
  <div class="supply-config-panel">
    <!-- 传送指令设置（需求7：三个指令均可自定义） -->
    <el-card class="panel" header="补货传送指令（可自定义）">
      <el-form label-width="130px" size="small" class="cfg-form">
        <el-form-item label="前往补给点">
          <el-input v-model="cfg.go" placeholder="/ehomes mdssj" />
        </el-form-item>
        <el-form-item label="暂存当前位置">
          <el-input v-model="cfg.save" placeholder="/esethomes dth" />
        </el-form-item>
        <el-form-item label="返回工作位置">
          <el-input v-model="cfg.returnCmd" placeholder="/ehomes dth" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="small" :loading="savingCfg" @click="saveCfg">保存指令</el-button>
          <span class="cfg-hint">bot 物品用完补货时：先执行「暂存当前位置」→「前往补给点」取货 →「返回工作位置」</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 材料 ↔ 潜影盒坐标（需求6：每种材料定义对应潜影盒坐标） -->
    <el-card class="panel" header="补货潜影盒配置（材料 ↔ 坐标）">
      <p class="panel-desc">
        为任务需要的每种材料指定潜影盒坐标（世界坐标，玩家站在该坐标附近可交互）。
        bot 补货时按顺序取货，取空自动尝试下一个坐标；未配置坐标的材料回退旧补货方式。
      </p>
      <div v-loading="loading" class="mat-list">
        <div v-if="!items.length && !loading" class="empty">暂无材料需求（任务需先解析投影生成材料）</div>
        <div v-for="it in items" :key="it.item_id" class="mat-item">
          <div class="mat-head">
            <ItemIcon :item-id="it.item_id" :name="it.display_name" :size="26" class="mat-icon" />
            <span class="mat-name">{{ it.display_name || zhItemName(it.item_id) }}</span>
            <el-button size="small" text type="primary" @click="addBox(it)">+ 添加潜影盒</el-button>
          </div>
          <div class="box-list">
            <div v-for="(b, i) in it.boxes" :key="i" class="box-row">
              <span class="box-label mono">#{{ i + 1 }}</span>
              <el-input-number v-model="b.x" :controls="false" size="small" class="box-input" placeholder="X" />
              <el-input-number v-model="b.y" :controls="false" size="small" class="box-input" placeholder="Y" />
              <el-input-number v-model="b.z" :controls="false" size="small" class="box-input" placeholder="Z" />
              <el-button size="small" text type="danger" @click="removeBox(it, i)">删除</el-button>
            </div>
            <div v-if="!it.boxes.length" class="box-empty mono">未配置（回退旧补货方式）</div>
          </div>
        </div>
      </div>
      <div class="save-bar">
        <el-button type="primary" :loading="savingBoxes" :disabled="!items.length" @click="saveBoxes">
          保存潜影盒配置
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import ItemIcon from '@/components/ItemIcon.vue'
import { mapArtApi } from '@/api/mapArt'
import { errMsg } from '@/utils/error'
import { zhItemName } from '@/utils/itemZh'

const props = defineProps<{ taskId: string }>()

interface Box { x: number; y: number; z: number }
interface SupplyItem { item_id: string; display_name: string; boxes: Box[] }

const loading = ref(false)
const savingCfg = ref(false)
const savingBoxes = ref(false)
const items = ref<SupplyItem[]>([])
const cfg = reactive({ go: '/ehomes mdssj', save: '/esethomes dth', returnCmd: '/ehomes dth' })

async function load() {
  loading.value = true
  try {
    const [cfgResp, boxResp] = await Promise.all([
      mapArtApi.getSupplyConfig(props.taskId),
      mapArtApi.getSupplyBoxes(props.taskId),
    ])
    const c = cfgResp.data || {}
    cfg.go = c.go || '/ehomes mdssj'
    cfg.save = c.save || '/esethomes dth'
    cfg.returnCmd = c.return || c.return_ || '/ehomes dth'
    items.value = (boxResp.data?.items || []).map((it: any) => ({
      item_id: it.item_id,
      display_name: it.display_name || '',
      boxes: (it.boxes || []).map((b: any) => ({ x: b.x, y: b.y, z: b.z })),
    }))
  } catch (e) {
    ElMessage.error(errMsg(e, '加载补货配置失败'))
  } finally {
    loading.value = false
  }
}

async function saveCfg() {
  savingCfg.value = true
  try {
    await mapArtApi.saveSupplyConfig(props.taskId, {
      go: cfg.go.trim(),
      save: cfg.save.trim(),
      return: cfg.returnCmd.trim(),
    })
    ElMessage.success('传送指令已保存')
  } catch (e) {
    ElMessage.error(errMsg(e, '保存指令失败'))
  } finally {
    savingCfg.value = false
  }
}

function addBox(it: SupplyItem) {
  it.boxes.push({ x: 0, y: 0, z: 0 })
}
function removeBox(it: SupplyItem, idx: number) {
  it.boxes.splice(idx, 1)
}

async function saveBoxes() {
  savingBoxes.value = true
  try {
    const payload = items.value.map(it => ({
      item_id: it.item_id,
      boxes: it.boxes.filter(b => !(b.x === 0 && b.y === 0 && b.z === 0)),
    }))
    await mapArtApi.saveSupplyBoxes(props.taskId, payload)
    ElMessage.success('潜影盒配置已保存')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e, '保存潜影盒配置失败'))
  } finally {
    savingBoxes.value = false
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>

<style scoped>
.supply-config-panel { display: flex; flex-direction: column; gap: 12px; }
.panel { flex-shrink: 0; }
.cfg-form :deep(.el-form-item) { margin-bottom: 8px; }
.cfg-hint { font-size: 11px; color: var(--text-muted); margin-left: 8px; line-height: 1.5; }
.panel-desc { font-size: 12px; color: var(--text-muted); margin: 0 0 8px; line-height: 1.6; }
.mat-list { display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow-y: auto; }
.mat-item { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 8px 10px; }
.mat-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.mat-icon { flex-shrink: 0; border-radius: 3px; }
.mat-name { flex: 1; font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.box-list { display: flex; flex-direction: column; gap: 4px; }
.box-row { display: flex; align-items: center; gap: 6px; }
.box-label { width: 30px; color: var(--text-muted); font-size: 11px; }
.box-input { width: 90px; }
.box-empty { font-size: 11px; color: var(--text-muted); padding: 2px 0 2px 36px; }
.save-bar { margin-top: 10px; text-align: right; }
.empty { color: var(--text-muted); padding: 16px 0; text-align: center; font-size: 12px; }
</style>