import { defineStore } from 'pinia'
import { botApi } from '@/api/bot'

export interface MccBot {
  bot_id: string
  name: string
  status: string
  mc_username: string
  mc_server_host: string
  current_health: number
  current_food: number
  current_task_run_id: string | null
  current_build_task_id: string | null
  organization_id: string | null
}

export const useBotStore = defineStore('bot', {
  state: () => ({
    bots: [] as MccBot[],
    loading: false,
  }),
  getters: {
    onlineBots: (state) => state.bots.filter(b => b.status === 'online'),
    onlineCount: (state) => state.bots.filter(b => b.status === 'online').length,
    offlineCount: (state) => state.bots.filter(b => b.status !== 'online').length,
  },
  actions: {
    async fetchBots() {
      this.loading = true
      try {
        const { data } = await botApi.list()
        this.bots = data
      } finally {
        this.loading = false
      }
    },
    async createBot(botData: Partial<MccBot>) {
      const { data } = await botApi.create(botData as any)
      this.bots.push(data)
      return data
    },
    async connectBot(botId: string, config?: { host?: string; port?: number; auth_token?: string }) {
      const { data } = await botApi.connect(botId, config || {})
      this.updateBotFromSocket({ bot_id: botId, status: data.status })
      return data
    },
    async disconnectBot(botId: string) {
      await botApi.disconnect(botId)
      this.updateBotFromSocket({ bot_id: botId, status: 'offline' })
    },
    async deleteBot(botId: string) {
      await botApi.delete(botId)
      this.bots = this.bots.filter(b => b.bot_id !== botId)
    },
    updateBotFromSocket(payload: Partial<MccBot> & { bot_id: string }) {
      const idx = this.bots.findIndex(b => b.bot_id === payload.bot_id)
      if (idx >= 0) {
        Object.assign(this.bots[idx], payload)
      }
    },
  },
})
