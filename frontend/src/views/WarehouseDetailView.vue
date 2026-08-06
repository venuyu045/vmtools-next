<template>
  <div>
    <div class="page-header">
      <h2>仓库详情</h2>
      <div>
        <el-button @click="refreshAll">刷新</el-button>
        <el-button @click="$router.push('/warehouses')">返回列表</el-button>
      </div>
    </div>

    <!-- 仓库信息 -->
    <el-card v-if="warehouseStore.currentWarehouse" shadow="never" style="margin-bottom: 20px">
      <h3>{{ warehouseStore.currentWarehouse.name }}</h3>
      <p class="mono" style="color: var(--text-secondary); margin-top: 8px">
        容器: {{ fmtBigNum(warehouseStore.currentWarehouse.container_count) }} | 物品: {{ fmtBigNum(warehouseStore.currentWarehouse.total_items) }}
        <template v-if="warehouseStore.currentWarehouse.last_scan_time">
          | 上次扫描: {{ formatTime(warehouseStore.currentWarehouse.last_scan_time) }}
        </template>
      </p>
    </el-card>

    <!-- 仓库设置：前往仓库的传送指令 -->
    <el-card shadow="never" style="margin-bottom: 20px">
      <h3>仓库设置</h3>
      <div class="setting-row">
        <span class="setting-label">前往仓库指令：</span>
        <el-input
          v-model="teleportCmd"
          placeholder="例如 /tp 100 64 -200（扫描前 bot 会先执行该指令传送过去）"
          style="max-width: 480px"
          clearable
        />
        <el-button type="primary" :disabled="!teleportCmdChanged" @click="saveTeleportCmd">保存</el-button>
      </div>
      <p class="mono hint">提示：扫描时 bot 会先执行此指令传送到仓库，再扫描范围内容器（Servux 不打开容器）。</p>

      <el-divider />

      <h3>仓库范围（Storage Zones）</h3>
      <p class="mono hint">扫描时按这些范围枚举容器坐标（可添加多个范围，覆盖不同坐标的仓库区域）。</p>

      <el-table v-if="zones.length" :data="zones" style="margin: 12px 0" size="small" max-height="240">
        <el-table-column prop="name" label="名称" width="140" />
        <el-table-column label="范围 (min → max)" min-width="260">
          <template #default="{ row }">
            <span class="mono">X {{ row.range_min_x }}→{{ row.range_max_x }} | Y {{ row.range_min_y }}→{{ row.range_max_y }} | Z {{ row.range_min_z }}→{{ row.range_max_z }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="danger" @click="deleteZone(row.zone_id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无范围，请添加至少一个范围才能扫描" :image-size="60" />

      <div class="zone-form">
        <el-input v-model="zoneForm.name" placeholder="范围名称（如 A区）" style="width: 140px" />
        <el-input-number v-model="zoneForm.minX" :controls="false" placeholder="minX" style="width: 110px" />
        <el-input-number v-model="zoneForm.minY" :controls="false" placeholder="minY" style="width: 110px" />
        <el-input-number v-model="zoneForm.minZ" :controls="false" placeholder="minZ" style="width: 110px" />
        <span class="mono">→</span>
        <el-input-number v-model="zoneForm.maxX" :controls="false" placeholder="maxX" style="width: 110px" />
        <el-input-number v-model="zoneForm.maxY" :controls="false" placeholder="maxY" style="width: 110px" />
        <el-input-number v-model="zoneForm.maxZ" :controls="false" placeholder="maxZ" style="width: 110px" />
        <el-button type="primary" @click="addZone">添加范围</el-button>
      </div>
    </el-card>

    <!-- 扫描控制 -->
    <el-card shadow="never" style="margin-bottom: 20px">
      <h3>容器扫描（Servux 容器预览 · 不打开容器）</h3>
      <div class="scan-control">
        <el-select
          v-model="selectedBot"
          placeholder="选择扫描用 Bot（mineflayer）"
          style="width: 260px; margin-right: 12px"
          filterable
        >
          <el-option
            v-for="b in availableBots"
            :key="b.bot_id"
            :label="`${b.name} (${b.status})`"
            :value="b.bot_id"
          />
        </el-select>

        <el-button v-if="!isScanning" type="primary" :disabled="!selectedBot" @click="startScan">
          开始扫描
        </el-button>
        <template v-else>
          <el-button v-if="warehouseStore.scanStatus === 'scanning'" @click="control('pause')">暂停</el-button>
          <el-button v-if="warehouseStore.scanStatus === 'paused'" type="warning" @click="control('resume')">继续</el-button>
          <el-button type="danger" @click="control('cancel')">取消</el-button>
        </template>
      </div>

      <div v-if="isScanning || warehouseStore.scanTotal > 0" class="scan-progress">
        <el-progress
          :percentage="warehouseStore.scanProgress"
          :status="warehouseStore.scanStatus === 'finished' ? 'success' : warehouseStore.scanStatus === 'failed' ? 'exception' : undefined"
          style="margin-top: 12px"
        />
        <p class="mono scan-hint">
          状态: {{ statusText }}
          <template v-if="warehouseStore.scanScanned || warehouseStore.scanTotal">
            | {{ warehouseStore.scanScanned }}/{{ warehouseStore.scanTotal }} 容器
          </template>
          <template v-if="warehouseStore.scanItems">
            | {{ warehouseStore.scanItems.toLocaleString() }} 物品
          </template>
          <template v-if="warehouseStore.scanSpeed > 0">
            | {{ warehouseStore.scanSpeed }} 容器/秒
            <template v-if="warehouseStore.scanEta != null">| 预计剩余 {{ formatEta(warehouseStore.scanEta) }}</template>
          </template>
          <template v-if="queuePosition != null">
            | 排队中（前面还有 {{ queuePosition }} 个任务）
          </template>
          <template v-if="warehouseStore.scanCurrentPos">
            | 当前: {{ warehouseStore.scanCurrentPos.x }},{{ warehouseStore.scanCurrentPos.y }},{{ warehouseStore.scanCurrentPos.z }}
          </template>
        </p>
      </div>
    </el-card>

    <!-- 材料列表 -->
    <el-card shadow="never">
      <h3>材料列表 <span class="mono count-badge">{{ warehouseStore.materialTotal }} 种</span></h3>
      <el-table :data="warehouseStore.materials" style="width: 100%; margin-top: 12px" max-height="600">
        <el-table-column prop="item_id" label="物品 ID" show-overflow-tooltip />
        <el-table-column prop="display_name" label="名称" width="200" />
        <el-table-column label="数量" width="150" sortable prop="count">
          <template #default="{ row }">
            <span :title="`≈ ${boxCount(row.count)}盒`">{{ fmtExact(row.count) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="warehouseStore.materials.length === 0" description="暂无材料数据，请先扫描仓库" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElNotification, ElMessage } from 'element-plus'
import { useWarehouseStore, type WarehouseZone } from '@/stores/warehouse'
import { useBotStore } from '@/stores/bot'
import { useMccInstanceStore } from '@/stores/mccInstance'
import { useSocketIO } from '@/composables/useSocketIO'
import { warehouseApi } from '@/api/warehouse'
import { boxCount, fmtBigNum, fmtExact } from '@/utils/format'

const route = useRoute()
const warehouseStore = useWarehouseStore()
const botStore = useBotStore()
const mccStore = useMccInstanceStore()
const { emit, getSocket } = useSocketIO()

const warehouseId = computed(() => route.params.id as string)
const selectedBot = ref('')

// 仓库设置
const teleportCmd = ref('')
const teleportCmdChanged = computed(() => teleportCmd.value !== (warehouseStore.currentWarehouse?.teleport_cmd ?? warehouseStore.currentWarehouse?.logistics_teleport_cmd ?? ''))
const zones = ref<WarehouseZone[]>([])
const zoneForm = ref({
  name: '', minX: 0, minY: 0, minZ: 0, maxX: 0, maxY: 0, maxZ: 0,
})

async function fetchZones() {
  try {
    const { data } = await warehouseApi.getZones(warehouseId.value)
    zones.value = data ?? []
  } catch { zones.value = [] }
}

async function saveTeleportCmd() {
  await warehouseStore.updateWarehouse(warehouseId.value, { teleport_cmd: teleportCmd.value })
  ElMessage.success('传送指令已保存')
  await refreshAll()
}

async function addZone() {
  const f = zoneForm.value
  if (!f.name) { ElMessage.warning('请输入范围名称'); return }
  if (f.maxX < f.minX || f.maxY < f.minY || f.maxZ < f.minZ) {
    ElMessage.warning('max 必须 ≥ min')
    return
  }
  await warehouseApi.createZone(warehouseId.value, {
    name: f.name,
    range_min_x: f.minX, range_min_y: f.minY, range_min_z: f.minZ,
    range_max_x: f.maxX, range_max_y: f.maxY, range_max_z: f.maxZ,
  })
  ElMessage.success('范围已添加')
  zoneForm.value = { name: '', minX: 0, minY: 0, minZ: 0, maxX: 0, maxY: 0, maxZ: 0 }
  await fetchZones()
}

async function deleteZone(zoneId: string) {
  await warehouseApi.deleteZone(warehouseId.value, zoneId)
  ElMessage.success('范围已删除')
  await fetchZones()
}

const availableBots = computed(() => {
  // 仓库扫描走 Servux（mineflayer），只列出 Mineflayer 引擎实例绑定的 Bot
  const mfBotIds = new Set(
    mccStore.instances
      .filter(i => (i.bot_engine || '') === 'mineflayer' && i.bot_id)
      .map(i => i.bot_id as string)
  )
  return botStore.bots.filter(b => mfBotIds.has(b.bot_id))
})

const isScanning = computed(() =>
  ['scanning', 'paused', 'queued'].includes(warehouseStore.scanStatus)
)
const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲',
    queued: '排队中',
    scanning: '扫描中',
    paused: '已暂停',
    finished: '已完成',
    cancelled: '已取消',
    failed: '失败',
  }
  return map[warehouseStore.scanStatus] || warehouseStore.scanStatus
})
// 当前仓库在扫描队列中的位置（排队中时显示）
const queuePosition = computed<number | null>(() => {
  const items = warehouseStore.scanQueue.filter(
    (q: any) => q.warehouse_id === warehouseId.value && ['pending', 'paused'].includes(q.status)
  )
  if (!items.length) return null
  // 计算排在当前任务前面（更早创建）的 pending 任务数
  const myCreated = items[0].created_at
  const ahead = warehouseStore.scanQueue.filter(
    (q: any) => q.status === 'pending' && q.created_at && myCreated && q.created_at < myCreated
  ).length
  return ahead
})
function formatEta(seconds: number | null) {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return '--'
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h${m}m`
  if (m > 0) return `${m}m${sec}s`
  return `${sec}s`
}

function formatTime(iso: string | null) {
  if (!iso) return '--'
  return new Date(iso).toLocaleString()
}

async function refreshAll() {
  await Promise.all([
    warehouseStore.fetchWarehouse(warehouseId.value),
    warehouseStore.fetchMaterials(warehouseId.value),
    warehouseStore.fetchScanStatus(warehouseId.value),
    fetchZones(),
  ])
  teleportCmd.value = warehouseStore.currentWarehouse?.teleport_cmd ?? warehouseStore.currentWarehouse?.logistics_teleport_cmd ?? ''
}

function startScan() {
  if (!selectedBot.value) return
  emit('scan_control', {
    action: 'start',
    warehouse_id: warehouseId.value,
    bot_id: selectedBot.value,
  })
  warehouseStore.scanStatus = 'scanning'
  warehouseStore.scanProgress = 0
}

function control(action: string) {
  emit('scan_control', { action, warehouse_id: warehouseId.value })
}

function onScanProgress(payload: any) {
  if (payload?.warehouse_id === warehouseId.value) {
    warehouseStore.setScanProgress(payload)
  }
}

function onScanAlert(payload: any) {
  if (!payload?.warehouse_id || payload.warehouse_id === warehouseId.value) {
    if (payload?.message) {
      ElNotification({
        title: payload.type === 'error' ? '扫描错误' : payload.type === 'success' ? '扫描完成' : '扫描提示',
        message: payload.message,
        type: payload.type === 'error' ? 'error' : payload.type === 'success' ? 'success' : 'info',
        duration: 4000,
      })
    }
    // 结束后刷新材料与状态
    if (['finished', 'cancelled', 'failed', 'success'].includes(payload?.type)) {
      refreshAll()
    }
  }
}

function onScanQueueUpdate(payload: any) {
  warehouseStore.setScanQueue(payload?.items ?? [])
  // 若当前仓库有新队列项，同步 scan_status
  const mine = (payload?.items ?? []).find((q: any) => q.warehouse_id === warehouseId.value)
  if (mine) {
    warehouseStore.scanStatus = mine.status === 'running' ? 'scanning' : mine.status
    if (mine.status === 'running') {
      warehouseStore.scanScanned = mine.scanned_containers || 0
      warehouseStore.scanTotal = mine.total_containers || 0
      warehouseStore.scanItems = mine.items_scanned || 0
    }
  }
}

onMounted(async () => {
  await Promise.all([botStore.fetchBots(), mccStore.fetchInstances(), refreshAll(), warehouseStore.fetchScanQueue()])
  getSocket()?.on('scan_progress', onScanProgress)
  getSocket()?.on('scan_alert', onScanAlert)
  getSocket()?.on('scan_queue_update', onScanQueueUpdate)
})
onBeforeUnmount(() => {
  getSocket()?.off('scan_progress', onScanProgress)
  getSocket()?.off('scan_alert', onScanAlert)
  getSocket()?.off('scan_queue_update', onScanQueueUpdate)
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.scan-control { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.scan-progress { margin-top: 8px; }
.scan-hint { color: var(--text-secondary); margin-top: 6px; font-size: 13px; }
.count-badge { color: var(--text-secondary); font-size: 13px; margin-left: 8px; }
.setting-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.setting-label { white-space: nowrap; }
.hint { color: var(--text-secondary); font-size: 13px; margin-top: 4px; }
.zone-form { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .page-header { flex-direction: column; align-items: flex-start; gap: 10px; }
  .setting-row { flex-direction: column; align-items: stretch; }
  .setting-row .el-input { max-width: 100% !important; }
  .zone-form { align-items: stretch; }
  .zone-form .el-input,
  .zone-form .el-input-number { width: calc(50% - 4px) !important; }
  .scan-control { align-items: stretch; }
  .scan-control .el-select { width: 100% !important; margin-right: 0 !important; }
  .scan-control .el-button { margin-left: 0; }
  .scan-hint { font-size: 12px; line-height: 1.6; }
  /* 表格横向滚动（el-table 自带，确保不挤压列） */
  :deep(.el-table) { min-width: 560px; }
}
@media (max-width: 480px) {
  .zone-form .el-input,
  .zone-form .el-input-number { width: 100% !important; }
  :deep(.el-table) { min-width: 480px; }
}
</style>