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
  net_sent_rate?: number
  net_recv_rate?: number
}

export interface ProcessSample {
  name: string
  pid: number
  cpu_percent: number
  mem_mb: number
  cmdline: string
  role: string
  instance_id?: string | null
  instance_name?: string | null
}

export interface AlertEvent {
  timestamp: number
  name: string
  severity: string
  metric_name: string
  value: number
  operator: string
  threshold: number
  message: string
}

export const useMonitorStore = defineStore('monitor', {
  state: () => ({
    metrics: [] as MetricSample[],
    alerts: [] as any[],
    alertEvents: [] as AlertEvent[],
    processes: [] as ProcessSample[],
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
    async fetchAlertEvents(count = 100) {
      const { data } = await monitorApi.getAlertEvents(count)
      this.alertEvents = data
    },
    async fetchProcesses() {
      const { data } = await monitorApi.getProcesses()
      this.processes = data
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
    pushProcesses(payload: ProcessSample[]) {
      if (Array.isArray(payload)) this.processes = payload
    },
    pushAlertEvent(payload: AlertEvent) {
      this.alertEvents.unshift(payload)
      if (this.alertEvents.length > 100) {
        this.alertEvents = this.alertEvents.slice(0, 100)
      }
    },
  },
})
