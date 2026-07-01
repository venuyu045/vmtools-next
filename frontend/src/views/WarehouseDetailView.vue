<template>
  <div>
    <div class="page-header">
      <h2>仓库详情</h2>
      <el-button @click="$router.push('/warehouses')">返回列表</el-button>
    </div>
    <el-card v-if="warehouseStore.currentWarehouse" shadow="never" style="margin-bottom: 20px">
      <h3>{{ warehouseStore.currentWarehouse.name }}</h3>
      <p class="mono" style="color: var(--text-secondary); margin-top: 8px">
        容器: {{ warehouseStore.currentWarehouse.container_count }} | 物品: {{ warehouseStore.currentWarehouse.total_items }}
      </p>
    </el-card>
    <el-card shadow="never">
      <h3>材料列表</h3>
      <el-table :data="warehouseStore.materials" style="width: 100%; margin-top: 12px">
        <el-table-column prop="item_id" label="物品 ID" show-overflow-tooltip />
        <el-table-column prop="display_name" label="名称" width="200" />
        <el-table-column prop="count" label="数量" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useWarehouseStore } from '@/stores/warehouse'

const route = useRoute()
const warehouseStore = useWarehouseStore()

onMounted(async () => {
  const id = route.params.id as string
  await warehouseStore.fetchWarehouse(id)
  await warehouseStore.fetchMaterials(id)
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
