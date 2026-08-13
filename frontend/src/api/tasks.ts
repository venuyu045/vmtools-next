import client from './client'

/** 任务中心：统一任务列表 + 统计 + Bot 执行视角（只读聚合） */
export const tasksApi = {
  getOverview() {
    return client.get('/tasks/overview')
  },
  /** 任务管理：所有 MF bot + 手动工作标记 + 当前系统工作（2026-08-13） */
  getManualWork() {
    return client.get('/tasks/manual-work')
  },
  /** 设置 bot 手动工作标记（working=True 时 name 必填） */
  setManualWork(botId: string, working: boolean, name: string) {
    return client.put(`/tasks/manual-work/${botId}`, { working, name })
  },
  /** 定时任务（2026-08-13 任务管理页） */
  listScheduled() {
    return client.get('/tasks/scheduled')
  },
  createScheduled(payload: {
    name: string
    task_type: string
    target_id: string
    bot_ids: string[]
    schedule_kind: string
    run_at?: string | null
    schedule_time?: string
    schedule_weekday?: number
    auto_manage?: boolean
  }) {
    return client.post('/tasks/scheduled', payload)
  },
  updateScheduled(taskId: string, payload: { enabled?: boolean; name?: string; auto_manage?: boolean }) {
    return client.put(`/tasks/scheduled/${taskId}`, payload)
  },
  deleteScheduled(taskId: string) {
    return client.delete(`/tasks/scheduled/${taskId}`)
  },
}
