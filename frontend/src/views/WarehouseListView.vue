<template>
  <div>
    <div class="page-header">
      <button class="pixel-btn" @click="showCreate = true">+ 新建仓库</button>
    </div>
    <div class="wh-grid">
      <div v-if="warehouseStore.warehouses.length === 0" class="empty-text mono">
        -- 暂无仓库，点击上方按钮创建 --
      </div>
      <div
        v-for="wh in warehouseStore.warehouses"
        :key="wh.warehouse_id"
        class="wh-card pixel-card"
        @click="$router.push(`/warehouses/${wh.warehouse_id}`)"
      >
        <div class="wh-header">
          <h3 class="wh-name pixel">{{ wh.name }}</h3>
          <span class="pixel-badge green">
            <span class="badge-dot"></span>
            已同步
          </span>
        </div>
        <div class="wh-stats">
          <div class="wh-stat">
            <span class="wh-stat-val pixel" :title="fmtExact(wh.total_items)">{{ fmtBigNum(wh.total_items || 0) }}</span>
            <span class="wh-stat-lbl mono">物品数</span>
          </div>
          <div class="wh-stat">
            <span class="wh-stat-val pixel" style="color: #ffff00">{{ fmtBigNum(wh.container_count || 0) }}</span>
            <span class="wh-stat-lbl mono">容器数</span>
          </div>
          <div class="wh-stat">
            <span class="wh-stat-val pixel" style="color: #1890ff">{{ wh.material_count || 0 }}</span>
            <span class="wh-stat-lbl mono">物品种类</span>
          </div>
          <div class="wh-stat">
            <span class="wh-stat-val pixel" style="font-size: 13px">{{ fmtTime(wh.last_scan_time) }}</span>
            <span class="wh-stat-lbl mono">上次扫描</span>
          </div>
        </div>
        <div class="wh-actions">
          <button class="pixel-btn" style="flex: 1; padding: 10px 0; font-size: 13px">详情</button>
          <button class="pixel-btn outline" style="flex: 1; padding: 10px 0; font-size: 13px">扫描</button>
        </div>
      </div>
    </div>
    <el-dialog v-model="showCreate" title="创建仓库" width="480px">
    <el-form :model="createForm" label-width="100px">
      <el-form-item label="名称">
        <el-input v-model="createForm.name" placeholder="仓库名称" />
      </el-form-item>
      <el-form-item label="前往指令">
        <el-input v-model="createForm.teleport_cmd" placeholder="例如 /tp 100 64 -200（可稍后编辑）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showCreate = false">取消</el-button>
      <el-button type="primary" @click="handleCreate">创建</el-button>
    </template>
  </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useWarehouseStore } from '@/stores/warehouse'
import { ElMessage } from 'element-plus'
import { fmtBigNum, fmtExact } from '@/utils/format'

function fmtTime(iso: string | null): string {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

const warehouseStore = useWarehouseStore()
const showCreate = ref(false)
  const createForm = ref({ name: '', teleport_cmd: '' })

  async function handleCreate() {
    if (!createForm.value.name) {
      ElMessage.warning('请输入仓库名称')
      return
    }
    await warehouseStore.createWarehouse(createForm.value.name, createForm.value.teleport_cmd)
    showCreate.value = false
    createForm.value = { name: '', teleport_cmd: '' }
    ElMessage.success('仓库已创建')
  }

onMounted(() => warehouseStore.fetchWarehouses())
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.wh-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.empty-text { color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
.wh-card { cursor: pointer; min-width: 0; }
.wh-card:hover { border-color: var(--border-active); }
.wh-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; min-width: 0; }
.wh-name { font-size: 14px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-stats { display: flex; gap: 0; margin-bottom: 16px; min-width: 0; }
.wh-stat { flex: 1; display: flex; flex-direction: column; gap: 4px; padding-right: 20px; min-width: 0; }
.wh-stat:last-child { padding-right: 0; }
.wh-stat-val { font-size: 20px; color: var(--green-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-stat-lbl { font-size: 14px; color: var(--text-secondary); }
.wh-actions { display: flex; gap: 8px; }
@media (max-width: 1000px) { .wh-grid { grid-template-columns: 1fr; } }

/* ============ 移动端适配 ============ */
@media (max-width: 768px) {
  .page-header { display: flex; }
  .page-header .pixel-btn { width: 100%; padding: 12px 0; font-size: 14px; }
  .wh-header { margin-bottom: 14px; }
  .wh-stats { flex-wrap: wrap; }
  .wh-stat { min-width: 50%; padding-right: 8px; }
  .wh-stat:nth-child(3) { min-width: 100%; padding-top: 8px; }
  .wh-stat-val { font-size: 18px; }
  .wh-stat-lbl { font-size: 13px; }
}
@media (max-width: 480px) {
  .wh-stat-val { font-size: 16px; }
}
</style>
