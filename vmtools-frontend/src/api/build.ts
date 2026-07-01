import client from './client'

export const buildApi = {
  listTasks() {
    return client.get('/build/tasks')
  },
  getTask(id: string) {
    return client.get(`/build/tasks/${id}`)
  },
  createTask(data: {
    bot_id: string
    projection_file_path: string
    projection_name?: string
    origin_x?: number
    origin_y?: number
    origin_z?: number
    layer_height?: number
  }) {
    return client.post('/build/tasks', data)
  },
  startTask(id: string) {
    return client.post(`/build/tasks/${id}/start`)
  },
  pauseTask(id: string) {
    return client.post(`/build/tasks/${id}/pause`)
  },
  resumeTask(id: string) {
    return client.post(`/build/tasks/${id}/resume`)
  },
  cancelTask(id: string) {
    return client.post(`/build/tasks/${id}/cancel`)
  },
  uploadProjection(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return client.post('/projections/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  listProjections() {
    return client.get('/projections')
  },
  getProjection(id: string) {
    return client.get(`/projections/${id}`)
  },
  compareProjection(id: string, warehouseId?: string) {
    return client.get(`/projections/${id}/compare`, { params: { warehouse_id: warehouseId } })
  },
}
