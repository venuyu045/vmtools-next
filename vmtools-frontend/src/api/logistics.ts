import client from './client'

export const logisticsApi = {
  // Waypoints
  listWaypoints(params?: { page?: number; page_size?: number }) {
    return client.get('/logistics/waypoints', { params })
  },
  getWaypoint(id: string) {
    return client.get(`/logistics/waypoints/${id}`)
  },
  createWaypoint(data: any) {
    return client.post('/logistics/waypoints', data)
  },
  updateWaypoint(id: string, data: any) {
    return client.put(`/logistics/waypoints/${id}`, data)
  },
  deleteWaypoint(id: string) {
    return client.delete(`/logistics/waypoints/${id}`)
  },

  // Drop Points
  listDropPoints(params?: { page?: number; page_size?: number }) {
    return client.get('/logistics/drop-points', { params })
  },
  getDropPoint(id: string) {
    return client.get(`/logistics/drop-points/${id}`)
  },
  createDropPoint(data: any) {
    return client.post('/logistics/drop-points', data)
  },
  updateDropPoint(id: string, data: any) {
    return client.put(`/logistics/drop-points/${id}`, data)
  },
  deleteDropPoint(id: string) {
    return client.delete(`/logistics/drop-points/${id}`)
  },

  // Task Templates
  listTemplates(params?: { page?: number; page_size?: number }) {
    return client.get('/logistics/task-templates', { params })
  },
  getTemplate(id: string) {
    return client.get(`/logistics/task-templates/${id}`)
  },
  createTemplate(data: any) {
    return client.post('/logistics/task-templates', data)
  },
  updateTemplate(id: string, data: any) {
    return client.put(`/logistics/task-templates/${id}`, data)
  },
  deleteTemplate(id: string) {
    return client.delete(`/logistics/task-templates/${id}`)
  },
  toggleTemplate(id: string) {
    return client.patch(`/logistics/task-templates/${id}/toggle`)
  },

  // Task Runs
  listRuns(params?: { page?: number; page_size?: number; status?: string; bot_id?: string }) {
    return client.get('/logistics/task-runs', { params })
  },
  getRun(id: string) {
    return client.get(`/logistics/task-runs/${id}`)
  },
  getRunLogs(id: string, params?: { page?: number; page_size?: number }) {
    return client.get(`/logistics/task-runs/${id}/logs`, { params })
  },
  startTask(data: { template_id: string; bot_id: string }) {
    return client.post('/logistics/tasks/start', data)
  },
  stopTask(id: string) {
    return client.post(`/logistics/tasks/${id}/stop`)
  },
  pauseTask(id: string) {
    return client.post(`/logistics/tasks/${id}/pause`)
  },
  resumeTask(id: string) {
    return client.post(`/logistics/tasks/${id}/resume`)
  },
}
