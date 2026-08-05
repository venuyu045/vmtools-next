<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useSocketIO } from '@/composables/useSocketIO'

const authStore = useAuthStore()
const { connect, disconnect } = useSocketIO()

onMounted(() => {
  if (authStore.isLoggedIn) {
    authStore.getMe()
    connect()
  }
})

// Watch for login/logout
watch(() => authStore.isLoggedIn, (loggedIn) => {
  if (loggedIn) {
    connect()
  } else {
    disconnect()
  }
})

onUnmounted(() => {
  disconnect()
})
</script>
