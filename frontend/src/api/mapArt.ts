import client from './client'

export const mapArtApi = {
  listTasks(params?: { status?: string }) {
    return client.get('/build/map-art/tasks', { params })
  },
  getTask(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}`)
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
    return client.post('/build/map-art/tasks', data)
  },
  controlTask(taskId: string, action: string) {
    return client.post(`/build/map-art/tasks/${taskId}/control`, { action })
  },
  deleteTask(taskId: string) {
    return client.delete(`/build/map-art/tasks/${taskId}`)
  },
  uploadProjection(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post('/build/map-art/projections/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  getBlocks(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/blocks`)
  },
  /** P1-5：轻量增量——只返回已放置方块（供 2D 画布轮询刷新） */
  getPlacedBlocks(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/blocks/placed`)
  },
  /** P2-27：动态 bot 分配（运行中任务 add/remove） */
  manageBot(taskId: string, action: 'add' | 'remove', botId: string) {
    return client.post(`/build/map-art/tasks/${taskId}/bots`, { action, bot_id: botId })
  },
}
