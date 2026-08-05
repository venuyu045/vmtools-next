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
        容器: {{ warehouseStore.currentWarehouse.container_count }} | 物品: {{ warehouseStore.currentWarehouse.total_items }}
        <template v-if="warehouseStore.currentWarehouse.last_scan_time">
          | 上次扫描: {{ formatTime(warehouseStore.currentWarehouse.last_scan_time) }}
        </template>
      </p>
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
        <el-table-column prop="count" label="数量" width="120" sortable />
      </el-table>
      <el-empty v-if="warehouseStore.materials.length === 0" description="暂无材料数据，请先扫描仓库" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElNotification } from 'element-plus'
import { useWarehouseStore } from '@/stores/warehouse'
import { useBotStore } from '@/stores/bot'
import { useSocketIO } from '@/composables/useSocketIO'

const route = useRoute()
const warehouseStore = useWarehouseStore()
const botStore = useBotStore()
const { emit, getSocket } = useSocketIO()

const warehouseId = computed(() => route.params.id as string)
const selectedBot = ref('')

const availableBots = computed(() => botStore.bots)

const isScanning = computed(() =>
  ['scanning', 'paused'].includes(warehouseStore.scanStatus)
)

const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲',
    scanning: '扫描中',
    paused: '已暂停',
    finished: '已完成',
    cancelled: '已取消',
    failed: '失败',
  }
  return map[warehouseStore.scanStatus] || warehouseStore.scanStatus
})

function formatTime(iso: string | null) {
  if (!iso) return '--'
  return new Date(iso).toLocaleString()
}

async function refreshAll() {
  await Promise.all([
    warehouseStore.fetchWarehouse(warehouseId.value),
    warehouseStore.fetchMaterials(warehouseId.value),
    warehouseStore.fetchScanStatus(warehouseId.value),
  ])
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

onMounted(async () => {
  await Promise.all([botStore.fetchBots(), refreshAll()])
  getSocket()?.on('scan_progress', onScanProgress)
  getSocket()?.on('scan_alert', onScanAlert)
})

onBeforeUnmount(() => {
  getSocket()?.off('scan_progress', onScanProgress)
  getSocket()?.off('scan_alert', onScanAlert)
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.scan-control { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.scan-progress { margin-top: 8px; }
.scan-hint { color: var(--text-secondary); margin-top: 6px; font-size: 13px; }
.count-badge { color: var(--text-secondary); font-size: 13px; margin-left: 8px; }
</style>