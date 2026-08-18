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
    rotation?: number
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
  /** 2026-08-14 终端：活动日志（REST 轮询兜底，不依赖 socket） */
  getLogs(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/logs`)
  },
  /** 2026-08-14：正在工作的 bot 背包快照（实时终端下方 bot 背包面板轮询） */
  getBotsInventory(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/bots/inventory`)
  },
  /** P2-27：动态 bot 分配（运行中任务 add/remove） */
  manageBot(taskId: string, action: 'add' | 'remove', botId: string) {
    return client.post(`/build/map-art/tasks/${taskId}/bots`, { action, bot_id: botId })
  },
  /** 2026-08-14：补货传送指令（go/save/return 三个可自定义） */
  getSupplyConfig(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/supply-config`)
  },
  saveSupplyConfig(taskId: string, cfg: { go: string; save: string; return: string; return_fixed?: string }) {
    return client.put(`/build/map-art/tasks/${taskId}/supply-config`, cfg)
  },
  /** 2026-08-14 模块A：食物补货配置（猪排仓库指令 + 进食阈值） */
  getFoodConfig(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/food-config`)
  },
  saveFoodConfig(taskId: string, cfg: {
    item_id: string; go_command: string; wait_after_go_ms: number;
    eat_threshold_food: number; eat_threshold_health: number
  }) {
    return client.put(`/build/map-art/tasks/${taskId}/food-config`, cfg)
  },
  getFoodBoxes(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/food-boxes`)
  },
  saveFoodBoxes(taskId: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put(`/build/map-art/tasks/${taskId}/food-boxes`, { items })
  },
  /** 2026-08-16：睡觉点（床的方块坐标，世界坐标；未配置→跳过自动睡觉） */
  getSleepPoint(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/sleep-point`)
  },
  saveSleepPoint(taskId: string, sp: { x: number; y: number; z: number }) {
    return client.put(`/build/map-art/tasks/${taskId}/sleep-point`, sp)
  },
  /** 2026-08-18：手动触发任务内 bot 睡觉（「睡觉按钮」） */
  forceBotSleep(taskId: string, botId: string) {
    return client.post(`/build/map-art/tasks/${taskId}/bots/${botId}/sleep`)
  },
  /** 2026-08-18：查询 bot 实时世界时间/昼夜/睡觉状态（状态栏数据源） */
  getBotSleepStatus(botId: string) {
    return client.get(`/mcc-bots/${botId}/sleep/status`)
  },
  /** 2026-08-14：补货潜影盒坐标（材料 ↔ 坐标，1 材料可配多坐标） */
  getSupplyBoxes(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/supply-boxes`)
  },
  saveSupplyBoxes(taskId: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put(`/build/map-art/tasks/${taskId}/supply-boxes`, { items })
  },
  /** 2026-08-14 三期：全局补货仓库（材料→潜影盒，任务自动复用） */
  getSupplyWarehouse() {
    return client.get('/build/map-art/supply-warehouse')
  },
  saveSupplyWarehouse(items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put('/build/map-art/supply-warehouse', { items })
  },
  /** 2026-08-14 二期：补货潜影盒模板（可复用配置） */
  listSupplyTemplates() {
    return client.get('/build/map-art/supply-templates')
  },
  createSupplyTemplate(name: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.post('/build/map-art/supply-templates', { name, items })
  },
  updateSupplyTemplate(id: number, name: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put(`/build/map-art/supply-templates/${id}`, { name, items })
  },
  deleteSupplyTemplate(id: number) {
    return client.delete(`/build/map-art/supply-templates/${id}`)
  },
  applySupplyTemplate(id: number, taskId: string) {
    return client.post(`/build/map-art/supply-templates/${id}/apply`, { task_id: taskId })
  },
}
