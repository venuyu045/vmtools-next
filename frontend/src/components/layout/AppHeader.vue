<template>
  <div class="header">
    <div class="page-title" v-if="route.meta.title">
      > {{ route.meta.title }}
    </div>
    <div class="page-title" v-else>
      > VMTools
    </div>
    <div class="header-right">
      <span class="user-dot"></span>
      <span class="username">{{ authStore.user?.display_name || authStore.user?.game_id }}</span>
      <button class="logout-btn" @click="authStore.logout()">退出</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()
</script>

<style scoped>
.header {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  background: #0a0a0a;
  border-bottom: 1px solid var(--border-subtle);
}

.page-title {
  font-family: var(--font-pixel);
  font-size: 16px;
  color: var(--green-primary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-dot {
  width: 8px;
  height: 8px;
  background: var(--green-primary);
}

.username {
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--text-primary);
}

.logout-btn {
  background: none;
  border: 1px solid var(--border-card);
  color: var(--text-secondary);
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-body);
}

.logout-btn:hover {
  border-color: var(--border-active);
  color: var(--text-primary);
  background: var(--green-glow);
}
</style>
