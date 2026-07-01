import client from './client'

export const monitorApi = {
  getMetrics(count = 100) {
    return client.get('/monitor/metrics', { params: { count } })
  },
  getAlerts() {
    return client.get('/monitor/alerts')
  },
  getBotsSummary() {
    return client.get('/monitor/bots/summary')
  },
  health() {
    return client.get('/monitor/health')
  },
}
