import { defineStore } from 'pinia'
import { configApi } from '@/api/config'

export const useConfigStore = defineStore('config', {
  state: () => ({
    config: null as any,
    loading: false,
  }),
  actions: {
    async fetchConfig() {
      this.loading = true
      try {
        const { data } = await configApi.getConfig()
        this.config = data
      } finally {
        this.loading = false
      }
    },
    async reloadConfig() {
      const { data } = await configApi.reloadConfig()
      this.config = data.config
      return data
    },
  },
})
