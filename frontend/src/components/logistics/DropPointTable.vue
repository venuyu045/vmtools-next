<template>
  <div>
    <el-table :data="data" style="width: 100%">
      <el-table-column prop="drop_point_id" label="ID" width="280" show-overflow-tooltip />
      <el-table-column prop="name" label="名称" width="150" />
      <el-table-column prop="drop_method" label="方式" width="80" />
      <el-table-column label="坐标" width="200">
        <template #default="{ row }">
          <span class="mono">{{ row.drop_x }}, {{ row.drop_y }}, {{ row.drop_z }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="teleport_command" label="传送命令" show-overflow-tooltip />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="danger" plain @click="$emit('delete', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any[] }>()
defineEmits(['delete'])
</script>
