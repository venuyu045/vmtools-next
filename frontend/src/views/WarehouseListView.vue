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
            <span class="wh-stat-val pixel">{{ wh.total_items || 0 }}</span>
            <span class="wh-stat-lbl mono">物品数</span>
          </div>
          <div class="wh-stat">
            <span class="wh-stat-val pixel" style="color: #ffff00">{{ wh.container_count || 0 }}</span>
            <span class="wh-stat-lbl mono">容器数</span>
          </div>
          <div class="wh-stat">
            <span class="wh-stat-val pixel" style="font-size: 16px">{{ wh.last_scan_time || '--' }}</span>
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
      <el-form :model="createForm" label-width="60px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="仓库名称" />
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

const warehouseStore = useWarehouseStore()
const showCreate = ref(false)
const createForm = ref({ name: '' })

async function handleCreate() {
  if (!createForm.value.name) {
    ElMessage.warning('请输入仓库名称')
    return
  }
  await warehouseStore.createWarehouse(createForm.value.name)
  showCreate.value = false
  createForm.value.name = ''
  ElMessage.success('仓库已创建')
}

onMounted(() => warehouseStore.fetchWarehouses())
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.wh-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.empty-text { color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
.wh-card { cursor: pointer; }
.wh-card:hover { border-color: var(--border-active); }
.wh-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.wh-name { font-size: 14px; color: var(--text-primary); }
.wh-stats { display: flex; gap: 0; margin-bottom: 16px; }
.wh-stat { flex: 1; display: flex; flex-direction: column; gap: 4px; padding-right: 20px; }
.wh-stat:last-child { padding-right: 0; }
.wh-stat-val { font-size: 20px; color: var(--green-primary); }
.wh-stat-lbl { font-size: 14px; color: var(--text-secondary); }
.wh-actions { display: flex; gap: 8px; }
@media (max-width: 1000px) { .wh-grid { grid-template-columns: 1fr; } }
</style>
