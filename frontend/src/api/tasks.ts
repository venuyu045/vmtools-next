import client from './client'

/** 任务中心：统一任务列表 + 统计 + Bot 执行视角（只读聚合） */
export const tasksApi = {
  getOverview() {
    return client.get('/tasks/overview')
  },
}
