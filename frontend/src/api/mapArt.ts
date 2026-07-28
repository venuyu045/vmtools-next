import client from './client'

export const mapArtApi = {
  listTasks(params?: { status?: string }) {
    return client.get('/api/build/map-art/tasks', { params })
  },
  getTask(taskId: string) {
    return client.get(`/api/build/map-art/tasks/${taskId}`)
  },
  createTask(data: {
    name: string
    projection_file_path: string
    origin_x?: number
    origin_y?: number
    origin_z?: number
    bot_ids?: string[]
    organization_id?: string
  }) {
    return client.post('/api/build/map-art/tasks', data)
  },
  controlTask(taskId: string, action: string) {
    return client.post(`/api/build/map-art/tasks/${taskId}/control`, { action })
  },
  deleteTask(taskId: string) {
    return client.delete(`/api/build/map-art/tasks/${taskId}`)
  },
  uploadProjection(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post('/api/build/map-art/projections/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}
