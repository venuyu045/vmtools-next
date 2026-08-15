<template>
  <div class="supply-config-panel">
    <!-- 传送指令设置（需求7：三个指令均可自定义 + 2026-08-14 固定返回兜底） -->
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
        <el-form-item label="固定返回（兜底）">
          <el-input v-model="cfg.returnFixed" placeholder="/ehomes mapart" />
          <span class="cfg-hint">死亡/意外导致临时点（dth）不在地图画区域时，用此固定方式传回地图画（如 /ehomes mapart 或 /tp x y z）</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="small" :loading="savingCfg" @click="saveCfg">保存指令</el-button>
          <span class="cfg-hint">bot 物品用完补货时：先执行「暂存当前位置」→「前往补给点」取货 →「返回工作位置」；回建造点失败自动用「固定返回」兜底</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 材料 ↔ 潜影盒坐标（需求6：每种材料定义对应潜影盒坐标；2026-08-14 改为可折叠，配置一次后基本不用动） -->
    <el-card class="panel" header="补货潜影盒配置（材料 ↔ 坐标）">
      <div class="collapse-toggle">
        <el-button size="small" text type="primary" @click="boxesCollapsed = !boxesCollapsed">
          {{ boxesCollapsed ? '展开配置' : '收起配置' }}
        </el-button>
        <span class="cfg-hint">配置一次即可长期复用，可折叠收起</span>
      </div>
      <template v-if="!boxesCollapsed">
        <div class="panel-head-actions">
          <p class="panel-desc">
            为任务需要的每种材料指定潜影盒坐标（**填补货仓库所在维度的世界坐标**，玩家站在该坐标附近可交互）。
            bot 补货时按顺序取货，取空自动尝试下一个坐标；未配置坐标的材料回退旧补货方式。
          </p>
          <div class="tpl-actions">
            <el-button size="small" @click="syncFromWarehouse">从全局仓库同步</el-button>
            <el-button size="small" @click="openSaveTpl">保存为模板</el-button>
            <el-button size="small" @click="openImportTpl">从模板导入</el-button>
          </div>
        </div>
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
      </template>
    </el-card>

    <!-- 食物补货配置（2026-08-14 模块A：猪排仓库 + 进食阈值） -->
    <el-card class="panel" header="食物补货配置（副手猪排）">
      <el-form label-width="130px" size="small" class="cfg-form">
        <el-form-item label="食物类型">
          <el-input v-model="foodCfg.item_id" placeholder="minecraft:cooked_porkchop" />
        </el-form-item>
        <el-form-item label="前往猪排仓库">
          <el-input v-model="foodCfg.go_command" placeholder="/res tp lixiangxiang.qwp" />
        </el-form-item>
        <el-form-item label="指令后等待">
          <el-input-number v-model="foodCfg.wait_after_go_ms" :min="0" :max="60000" :step="1000" :controls="false" />
          <span class="cfg-hint">ms（指令自带 3s 延迟，默认 5000 更保险）</span>
        </el-form-item>
        <el-form-item label="进食阈值·饱食度">
          <el-input-number v-model="foodCfg.eat_threshold_food" :min="1" :max="20" :controls="false" />
          <span class="cfg-hint">低于该值（满 20）吃副手猪排</span>
        </el-form-item>
        <el-form-item label="进食阈值·血量">
          <el-input-number v-model="foodCfg.eat_threshold_health" :min="1" :max="20" :controls="false" />
          <span class="cfg-hint">低于该值吃副手猪排</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="small" :loading="savingFoodCfg" @click="saveFoodCfg">保存食物配置</el-button>
        </el-form-item>
      </el-form>

      <div class="panel-head-actions">
        <p class="panel-desc">
          猪排潜影盒坐标（填补货仓库所在维度的世界坐标）。bot 副手猪排不足时：
          保存当前位置 → 前往猪排仓库（等 5s）→ 取猪排 → 返回工作位置 → 装备副手。
        </p>
      </div>
      <div v-for="(b, i) in foodBoxes" :key="i" class="box-row">
        <span class="box-label mono">#{{ i + 1 }}</span>
        <el-input-number v-model="b.x" :controls="false" size="small" class="box-input" placeholder="X" />
        <el-input-number v-model="b.y" :controls="false" size="small" class="box-input" placeholder="Y" />
        <el-input-number v-model="b.z" :controls="false" size="small" class="box-input" placeholder="Z" />
        <el-button size="small" text type="danger" @click="foodBoxes.splice(i, 1)">删除</el-button>
      </div>
      <div class="save-bar">
        <el-button size="small" @click="foodBoxes.push({ x: 0, y: 0, z: 0 })">+ 添加潜影盒</el-button>
        <el-button type="primary" :loading="savingFoodBoxes" @click="saveFoodBoxes">保存潜影盒坐标</el-button>
      </div>
    </el-card>

    <!-- 保存为模板（2026-08-14 二期） -->
    <el-dialog v-model="saveTplOpen" title="保存为补货模板" width="400px" append-to-body>
      <p class="tpl-desc">把当前任务的潜影盒配置保存为可复用模板（仅含已配置坐标的材料），下个任务可一键导入。</p>
      <el-input v-model="saveTplName" placeholder="模板名称（如：混凝土补货）" />
      <template #footer>
        <el-button @click="saveTplOpen = false">取消</el-button>
        <el-button type="primary" :disabled="!saveTplName.trim()" :loading="savingTpl" @click="doSaveTpl">保存</el-button>
      </template>
    </el-dialog>

    <!-- 从模板导入（2026-08-14 二期） -->
    <el-dialog v-model="importTplOpen" title="从模板导入潜影盒配置" width="440px" append-to-body>
      <p class="tpl-desc">选择模板导入到当前任务（仅导入本任务需要的材料，覆盖当前配置）。</p>
      <el-select v-model="importTplId" placeholder="选择模板" style="width: 100%">
        <el-option v-for="t in tplList" :key="t.id" :label="`${t.name}（${t.material_count} 种材料）`" :value="t.id" />
      </el-select>
      <template #footer>
        <el-button @click="importTplOpen = false">取消</el-button>
        <el-button type="primary" :disabled="!importTplId" :loading="importingTpl" @click="doImportTpl">导入</el-button>
      </template>
    </el-dialog>
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
const cfg = reactive({ go: '/ehomes mdssj', save: '/esethomes dth', returnCmd: '/ehomes dth', returnFixed: '/ehomes mapart' })
// 2026-08-14：补货潜影盒配置默认折叠（配置一次后基本不用动）
const boxesCollapsed = ref(true)

// ── 食物补货（2026-08-14 模块A）──
const foodCfg = reactive({
  item_id: 'minecraft:cooked_porkchop',
  go_command: '/res tp lixiangxiang.qwp',
  wait_after_go_ms: 5000,
  eat_threshold_food: 15,
  eat_threshold_health: 15,
})
const foodBoxes = ref<Box[]>([])
const savingFoodCfg = ref(false)
const savingFoodBoxes = ref(false)

// ── 模板保存/导入（2026-08-14 二期） ──
const saveTplOpen = ref(false)
const saveTplName = ref('')
const savingTpl = ref(false)
const importTplOpen = ref(false)
const importTplId = ref<number | null>(null)
const importingTpl = ref(false)
const tplList = ref<any[]>([])

function openSaveTpl() {
  saveTplName.value = ''
  saveTplOpen.value = true
}

/** 2026-08-14 三期：从全局补货仓库同步本任务材料（未配置坐标的材料自动复用全局，任务级配置优先） */
async function syncFromWarehouse() {
  try {
    const { data } = await mapArtApi.getSupplyWarehouse()
    const globalMap = new Map<string, Box[]>()
    for (const it of ((data.items || []) as any[])) {
      globalMap.set(it.item_id, ((it.boxes || []) as any[]).map((b: any) => ({ x: b.x, y: b.y, z: b.z })))
    }
    let synced = 0
    for (const it of items.value) {
      const gBoxes = globalMap.get(it.item_id)
      if (gBoxes && gBoxes.length > 0 && it.boxes.length === 0) {
        it.boxes = gBoxes.map((b) => ({ x: b.x, y: b.y, z: b.z }))
        synced++
      }
    }
    ElMessage.success(synced > 0 ? `已同步 ${synced} 种材料的全局仓库坐标（保存后生效）` : '无新增（材料均已有配置或全局仓库无该材料）')
  } catch (e) {
    ElMessage.error(errMsg(e, '同步全局仓库失败'))
  }
}
async function doSaveTpl() {
  savingTpl.value = true
  try {
    const payload = items.value
      .map(it => ({ item_id: it.item_id, boxes: it.boxes.filter(b => !(b.x === 0 && b.y === 0 && b.z === 0)) }))
      .filter(it => it.boxes.length > 0)
    await mapArtApi.createSupplyTemplate(saveTplName.value.trim(), payload)
    ElMessage.success('已保存为模板')
    saveTplOpen.value = false
  } catch (e) {
    ElMessage.error(errMsg(e, '保存模板失败'))
  } finally {
    savingTpl.value = false
  }
}

async function openImportTpl() {
  importTplOpen.value = true
  importTplId.value = null
  try {
    const { data } = await mapArtApi.listSupplyTemplates()
    tplList.value = data.templates || []
    if (!tplList.value.length) ElMessage.info('暂无可用模板，可先在上方「保存为模板」创建')
  } catch (e) {
    ElMessage.error(errMsg(e, '加载模板列表失败'))
  }
}
async function doImportTpl() {
  if (!importTplId.value) return
  importingTpl.value = true
  try {
    const resp = await mapArtApi.applySupplyTemplate(importTplId.value, props.taskId)
    ElMessage.success(`已导入 ${resp.data?.saved ?? 0} 个潜影盒坐标`)
    importTplOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e, '导入模板失败'))
  } finally {
    importingTpl.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [cfgResp, boxResp, foodCfgResp, foodBoxResp] = await Promise.all([
      mapArtApi.getSupplyConfig(props.taskId),
      mapArtApi.getSupplyBoxes(props.taskId),
      mapArtApi.getFoodConfig(props.taskId),
      mapArtApi.getFoodBoxes(props.taskId),
    ])
    const c = cfgResp.data || {}
    cfg.go = c.go || '/ehomes mdssj'
    cfg.save = c.save || '/esethomes dth'
    cfg.returnCmd = c.return || c.return_ || '/ehomes dth'
    cfg.returnFixed = c.return_fixed || '/ehomes mapart'
    items.value = (boxResp.data?.items || []).map((it: any) => ({
      item_id: it.item_id,
      display_name: it.display_name || '',
      boxes: (it.boxes || []).map((b: any) => ({ x: b.x, y: b.y, z: b.z })),
    }))
    // 食物配置 + 猪排潜影盒（2026-08-14 模块A）
    const fc = foodCfgResp.data || {}
    foodCfg.item_id = fc.item_id || 'minecraft:cooked_porkchop'
    foodCfg.go_command = fc.go_command || '/res tp lixiangxiang.qwp'
    foodCfg.wait_after_go_ms = fc.wait_after_go_ms ?? 5000
    foodCfg.eat_threshold_food = fc.eat_threshold_food ?? 15
    foodCfg.eat_threshold_health = fc.eat_threshold_health ?? 15
    foodBoxes.value = (foodBoxResp.data?.boxes || []).map((b: any) => ({ x: b.x, y: b.y, z: b.z }))
  } catch (e) {
    ElMessage.error(errMsg(e, '加载补货配置失败'))
  } finally {
    loading.value = false
  }
}

async function saveFoodCfg() {
  savingFoodCfg.value = true
  try {
    await mapArtApi.saveFoodConfig(props.taskId, { ...foodCfg })
    ElMessage.success('食物配置已保存')
  } catch (e) {
    ElMessage.error(errMsg(e, '保存食物配置失败'))
  } finally {
    savingFoodCfg.value = false
  }
}

async function saveFoodBoxes() {
  savingFoodBoxes.value = true
  try {
    await mapArtApi.saveFoodBoxes(props.taskId, [{
      item_id: foodCfg.item_id,
      boxes: foodBoxes.value.filter(b => !(b.x === 0 && b.y === 0 && b.z === 0)),
    }])
    ElMessage.success('猪排潜影盒坐标已保存')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e, '保存猪排潜影盒坐标失败'))
  } finally {
    savingFoodBoxes.value = false
  }
}

async function saveCfg() {
  savingCfg.value = true
  try {
    await mapArtApi.saveSupplyConfig(props.taskId, {
      go: cfg.go.trim(),
      save: cfg.save.trim(),
      return: cfg.returnCmd.trim(),
      return_fixed: cfg.returnFixed.trim(),
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
.panel-head-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.collapse-toggle { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.tpl-actions { display: flex; gap: 6px; flex-shrink: 0; }
.tpl-desc { font-size: 12px; color: var(--text-muted); margin: 0 0 10px; line-height: 1.5; }
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