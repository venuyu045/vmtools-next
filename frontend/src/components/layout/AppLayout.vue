<template>
  <div class="app-layout">
    <aside class="app-sidebar">
      <AppSidebar />
    </aside>
    <div class="app-body">
      <header class="app-header">
        <AppHeader />
      </header>
      <main class="app-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
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
