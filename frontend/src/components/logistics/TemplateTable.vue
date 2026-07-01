<template>
  <div>
    <el-table :data="data" style="width: 100%">
      <el-table-column prop="template_id" label="ID" width="280" show-overflow-tooltip />
      <el-table-column prop="name" label="名称" width="200" />
      <el-table-column prop="loop_mode" label="模式" width="80" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? '已启用' : '已禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="$emit('toggle', row)">
            {{ row.enabled ? '禁用' : '启用' }}
          </el-button>
          <el-button size="small" type="danger" plain @click="$emit('delete', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any[] }>()
defineEmits(['toggle', 'delete'])
</script>
