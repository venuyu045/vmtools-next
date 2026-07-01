<template>
  <div>
    <div class="page-header">
      <h2>路径点管理</h2>
      <el-button type="primary" @click="showCreate = true">创建路径点</el-button>
    </div>
    <WaypointTable :data="logisticsStore.waypoints" @delete="handleDelete" />
    <el-dialog v-model="showCreate" title="创建路径点" width="600px">
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="名称"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="标识"><el-input v-model="createForm.key" /></el-form-item>
        <el-form-item label="物品名称"><el-input v-model="createForm.item_name" /></el-form-item>
        <el-form-item label="传送命令"><el-input v-model="createForm.teleport_command" /></el-form-item>
        <el-form-item label="容器坐标">
          <el-input-number v-model="createForm.container_x" :controls="false" style="width: 100px" />
          <el-input-number v-model="createForm.container_y" :controls="false" style="width: 100px; margin: 0 8px" />
          <el-input-number v-model="createForm.container_z" :controls="false" style="width: 100px" />
        </el-form-item>
        <el-form-item label="等待时间"><el-input-number v-model="createForm.wait_after_teleport" :min="0" /></el-form-item>
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
import { useLogisticsStore } from '@/stores/logistics'
import WaypointTable from '@/components/logistics/WaypointTable.vue'
import { ElMessage } from 'element-plus'

const logisticsStore = useLogisticsStore()
const showCreate = ref(false)
const createForm = ref({ name: '', key: '', item_name: '', teleport_command: '', container_x: 0, container_y: 0, container_z: 0, wait_after_teleport: 31 })

async function handleCreate() {
  await logisticsStore.createWaypoint(createForm.value)
  showCreate.value = false
  ElMessage.success('路径点已创建')
}

async function handleDelete(row: any) {
  await logisticsStore.deleteWaypoint(row.waypoint_id)
  ElMessage.success('已删除')
}

onMounted(() => logisticsStore.fetchWaypoints())
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
