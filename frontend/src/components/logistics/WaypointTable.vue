<template>
  <div>
    <el-table :data="data" style="width: 100%">
      <el-table-column prop="waypoint_id" label="ID" width="280" show-overflow-tooltip />
      <el-table-column prop="name" label="名称" width="150" />
      <el-table-column prop="key" label="标识" width="80" />
      <el-table-column prop="item_name" label="物品" width="120" />
      <el-table-column label="容器坐标" width="200">
        <template #default="{ row }">
          <span class="mono">{{ row.container_x }}, {{ row.container_y }}, {{ row.container_z }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="teleport_command" label="传送命令" show-overflow-tooltip />
      <el-table-column prop="wait_after_teleport" label="等待(s)" width="80" />
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
