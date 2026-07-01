import { defineStore } from 'pinia'
import { monitorApi } from '@/api/monitor'

export interface MetricSample {
  timestamp: number
  cpu_percent: number
  memory_percent: number
  memory_used: number
  memory_total: number
  disk_percent: number
  disk_used: number
  disk_total: number
  net_bytes_sent: number
  net_bytes_recv: number
}

export const useMonitorStore = defineStore('monitor', {
  state: () => ({
    metrics: [] as MetricSample[],
    alerts: [] as any[],
    botsSummary: { total: 0, online: 0, offline: 0 },
    loading: false,
  }),
  actions: {
    async fetchMetrics(count = 100) {
      this.loading = true
      try {
        const { data } = await monitorApi.getMetrics(count)
        this.metrics = data
      } finally {
        this.loading = false
      }
    },
    async fetchAlerts() {
      const { data } = await monitorApi.getAlerts()
      this.alerts = data
    },
    async fetchBotsSummary() {
      const { data } = await monitorApi.getBotsSummary()
      this.botsSummary = data
    },
    pushMetric(payload: MetricSample) {
      this.metrics.push(payload)
      if (this.metrics.length > 200) {
        this.metrics = this.metrics.slice(-200)
      }
    },
    pushAlert(payload: any) {
      this.alerts.unshift(payload)
      if (this.alerts.length > 100) {
        this.alerts = this.alerts.slice(0, 100)
      }
    },
  },
})
