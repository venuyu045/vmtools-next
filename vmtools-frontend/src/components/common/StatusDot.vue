<template>
  <span :class="['status-dot', status]" :title="status"></span>
</template>

<script setup lang="ts">
defineProps<{
  status: string
}>()
</script>

<style scoped>
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}
.status-dot.online,
.status-dot.running { background: var(--color-success); }
.status-dot.offline,
.status-dot.idle { background: var(--text-muted); }
.status-dot.error,
.status-dot.failed { background: var(--color-error); }
.status-dot.warning { background: var(--color-warning); }
.status-dot.paused { background: var(--color-info); }
.status-dot.pending { background: var(--text-secondary); }
.status-dot.completed { background: var(--color-success); }
</style>
