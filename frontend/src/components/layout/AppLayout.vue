<template>
  <div class="app-layout">
    <aside class="app-sidebar" :class="{ collapsed: isCollapsed }">
      <AppSidebar :collapsed="isCollapsed" @toggle="isCollapsed = !isCollapsed" />
    </aside>
    <div class="app-body">
      <header class="app-header">
        <AppHeader @toggle-sidebar="isCollapsed = !isCollapsed" />
      </header>
      <main class="app-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'

const isCollapsed = ref(false)
</script>

<style scoped>
.app-layout {
  height: 100vh;
  display: flex;
  background: #000;
}

.app-sidebar {
  width: 220px;
  flex-shrink: 0;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width 0.25s ease;
}

.app-sidebar.collapsed {
  width: 60px;
}

.app-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-header {
  height: 56px;
  flex-shrink: 0;
}

.app-main {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  background: #000;
}
</style>
