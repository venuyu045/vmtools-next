<template>
  <div class="empty-state">
    <el-icon :size="48"><component :is="iconComponent" /></el-icon>
    <p>{{ message }}</p>
    <slot></slot>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Box, Warning, Document, Search } from '@element-plus/icons-vue'

const props = defineProps<{
  icon?: string
  message: string
}>()

const iconComponent = computed(() => {
  const icons: Record<string, any> = { Box, Warning, Document, Search }
  return icons[props.icon || 'Box'] || Box
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
}
.empty-state p {
  margin-top: 12px;
  font-size: 14px;
}
</style>
