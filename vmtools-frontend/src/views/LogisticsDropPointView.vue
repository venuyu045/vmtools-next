<template>
  <div>
    <div class="page-header">
      <h2>投放点管理</h2>
      <el-button type="primary" @click="showCreate = true">创建投放点</el-button>
    </div>
    <DropPointTable :data="logisticsStore.dropPoints" @delete="handleDelete" />
    <el-dialog v-model="showCreate" title="创建投放点" width="600px">
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="名称"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="传送命令"><el-input v-model="createForm.teleport_command" /></el-form-item>
        <el-form-item label="投放方式">
          <el-select v-model="createForm.drop_method">
            <el-option label="扔出" value="drop" />
            <el-option label="放入容器" value="container" />
          </el-select>
        </el-form-item>
        <el-form-item label="投放坐标">
          <el-input-number v-model="createForm.drop_x" :controls="false" style="width: 100px" />
          <el-input-number v-model="createForm.drop_y" :controls="false" style="width: 100px; margin: 0 8px" />
          <el-input-number v-model="createForm.drop_z" :controls="false" style="width: 100px" />
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
import { useLogisticsStore } from '@/stores/logistics'
import DropPointTable from '@/components/logistics/DropPointTable.vue'
import { ElMessage } from 'element-plus'

const logisticsStore = useLogisticsStore()
const showCreate = ref(false)
const createForm = ref({ name: '', teleport_command: '', drop_method: 'drop', drop_x: 0, drop_y: 0, drop_z: 0 })

async function handleCreate() {
  await logisticsStore.createDropPoint(createForm.value)
  showCreate.value = false
  ElMessage.success('投放点已创建')
}

async function handleDelete(row: any) {
  await logisticsStore.deleteDropPoint(row.drop_point_id)
  ElMessage.success('已删除')
}

onMounted(() => logisticsStore.fetchDropPoints())
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
