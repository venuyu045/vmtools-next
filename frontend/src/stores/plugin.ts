import { defineStore } from 'pinia'
import { pluginApi } from '@/api/plugin'

export interface Plugin {
  name: string
  version: string
  enabled: boolean
  engine: string
  description: string
}

export const usePluginStore = defineStore('plugin', {
  state: () => ({
    plugins: [] as Plugin[],
    loading: false,
  }),
  actions: {
    async fetchPlugins() {
      this.loading = true
      try {
        const { data } = await pluginApi.listPlugins()
        this.plugins = data
      } finally {
        this.loading = false
      }
    },
    async togglePlugin(name: string) {
      const plugin = this.plugins.find(p => p.name === name)
      if (!plugin) return
      if (plugin.enabled) {
        await pluginApi.disablePlugin(name)
      } else {
        await pluginApi.enablePlugin(name)
      }
      // 后端失败会抛错（4xx/5xx），成功则重新拉取确保与真实状态一致
      await this.fetchPlugins()
    },
    async reloadPlugin(name: string) {
      await pluginApi.reloadPlugin(name)
    },
  },
})
