<template>
  <div>
    <div class="page-header">
      <h2>任务模板</h2>
      <el-button type="primary" @click="showCreate = true">创建模板</el-button>
    </div>
    <TemplateTable :data="logisticsStore.templates" @toggle="handleToggle" @delete="handleDelete" />
    <el-dialog v-model="showCreate" title="创建任务模板" width="600px">
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="名称"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="路径点 ID"><el-input v-model="createForm.source_waypoint_id" /></el-form-item>
        <el-form-item label="投放点 ID"><el-input v-model="createForm.drop_point_id" /></el-form-item>
        <el-form-item label="循环模式">
          <el-select v-model="createForm.loop_mode">
            <el-option label="单次" value="once" />
            <el-option label="循环" value="loop" />
          </el-select>
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
import TemplateTable from '@/components/logistics/TemplateTable.vue'
import { ElMessage } from 'element-plus'

const logisticsStore = useLogisticsStore()
const showCreate = ref(false)
const createForm = ref({ name: '', source_waypoint_id: '', drop_point_id: '', loop_mode: 'once' })

async function handleCreate() {
  await logisticsStore.createTemplate(createForm.value)
  showCreate.value = false
  ElMessage.success('模板已创建')
}

async function handleToggle(row: any) {
  await logisticsStore.toggleTemplate(row.template_id)
  ElMessage.success('已切换')
}

async function handleDelete(row: any) {
  await logisticsStore.deleteTemplate(row.template_id)
  ElMessage.success('已删除')
}

onMounted(() => logisticsStore.fetchTemplates())
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
